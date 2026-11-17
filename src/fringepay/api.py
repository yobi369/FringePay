"""HTTP routes for sandbox payment operations."""

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from fringepay.domain import Money
from fringepay.persistence import (
    PaymentRepository,
    PersistentIdempotencyConflict,
)
from fringepay.providers import PaymentCommand, SandboxProvider
from fringepay.service import CreatePayment

router = APIRouter(prefix="/payments", tags=["payments"])
sandbox_provider = SandboxProvider()


class CreatePaymentBody(BaseModel):
    amount_minor: int = Field(gt=0, strict=True)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    reference: str = Field(min_length=1, max_length=128)


class PaymentResponse(BaseModel):
    id: str
    amount_minor: int
    currency: str
    reference: str
    provider: str
    provider_reference: str | None
    status: str

    @classmethod
    def from_domain(cls, payment):
        return cls(
            id=payment.id,
            amount_minor=payment.amount.minor_units,
            currency=payment.amount.currency,
            reference=payment.reference,
            provider=payment.provider,
            provider_reference=payment.provider_reference,
            status=payment.status.value,
        )


@router.post("", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    body: CreatePaymentBody,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
) -> PaymentResponse:
    repository: PaymentRepository = request.app.state.repository
    create_request = CreatePayment(
        amount=Money(minor_units=body.amount_minor, currency=body.currency),
        reference=body.reference,
    )
    try:
        payment, created = await repository.reserve(create_request, idempotency_key)
        if created:
            provider_result = await sandbox_provider.initiate(
                PaymentCommand(
                    payment_id=payment.id,
                    amount=create_request.amount,
                    reference=create_request.reference,
                )
            )
            payment = await repository.apply_provider_result(
                payment.id,
                provider_result.status,
                provider_result.provider_reference,
            )
    except PersistentIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PaymentResponse.from_domain(payment)


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(payment_id: str, request: Request) -> PaymentResponse:
    repository: PaymentRepository = request.app.state.repository
    payment = await repository.get(payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    return PaymentResponse.from_domain(payment)
