"""HTTP routes for sandbox payment operations."""
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from fringepay.domain import Money, Payment
from fringepay.providers import SandboxProvider
from fringepay.service import CreatePayment, IdempotencyConflict, PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])
payment_service = PaymentService(SandboxProvider())

class CreatePaymentBody(BaseModel):
    amount_minor: int = Field(gt=0)
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
    def from_domain(cls, payment: Payment) -> "PaymentResponse":
        return cls(
            id=payment.id, amount_minor=payment.amount.minor_units,
            currency=payment.amount.currency, reference=payment.reference,
            provider=payment.provider, provider_reference=payment.provider_reference,
            status=payment.status.value,
        )

@router.post("", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    body: CreatePaymentBody,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
) -> PaymentResponse:
    request = CreatePayment(
        amount=Money(minor_units=body.amount_minor, currency=body.currency),
        reference=body.reference,
    )
    try:
        payment = await payment_service.create(request, idempotency_key)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PaymentResponse.from_domain(payment)

@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(payment_id: str) -> PaymentResponse:
    payment = payment_service.get(payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    return PaymentResponse.from_domain(payment)
