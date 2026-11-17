"""HTTP routes for sandbox payment operations."""

import hashlib

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError

from fringepay.config import get_settings
from fringepay.domain import InvalidPaymentTransition, Money, PaymentStatus
from fringepay.persistence import (
    PaymentRepository,
    PersistentIdempotencyConflict,
    WebhookReplayConflict,
)
from fringepay.providers import PaymentCommand, SandboxProvider
from fringepay.service import CreatePayment
from fringepay.webhooks import InvalidWebhookSignature, verify_hmac_webhook


async def require_api_key(
    request: Request,
    api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Resolve a tenant from a hashed, revocable API credential."""
    if api_key is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    repository: PaymentRepository = request.app.state.repository
    tenant_id = await repository.authenticate_api_key(api_key)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    request.state.tenant_id = tenant_id


router = APIRouter(
    prefix="/payments",
    tags=["payments"],
    dependencies=[Depends(require_api_key)],
)
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
        payment, _ = await repository.reserve(
            create_request, idempotency_key, tenant_id=request.state.tenant_id
        )
        claimed = await repository.claim_dispatch(payment.id)
        if claimed is not None:
            outbox_id, reserved_payment = claimed
            try:
                provider_result = await sandbox_provider.initiate(
                    PaymentCommand(
                        payment_id=reserved_payment.id,
                        amount=reserved_payment.amount,
                        reference=reserved_payment.reference,
                    )
                )
            except Exception as exc:
                await repository.retry_dispatch(outbox_id, "provider_dispatch_failed")
                raise HTTPException(
                    status_code=503,
                    detail="payment dispatch is temporarily unavailable",
                ) from exc
            payment = await repository.complete_dispatch(
                outbox_id,
                provider_result.status,
                provider_result.provider_reference,
            )
        else:
            payment = await repository.get(payment.id, request.state.tenant_id) or payment
    except PersistentIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PaymentResponse.from_domain(payment)


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(payment_id: str, request: Request) -> PaymentResponse:
    repository: PaymentRepository = request.app.state.repository
    payment = await repository.get(payment_id, request.state.tenant_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    return PaymentResponse.from_domain(payment)


webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class ProviderWebhookBody(BaseModel):
    payment_id: str = Field(min_length=1, max_length=36)
    status: PaymentStatus


@webhook_router.post("/{provider}")
async def receive_provider_webhook(
    provider: str,
    request: Request,
    signature: str = Header(alias="X-FringePay-Signature"),
    event_id: str = Header(alias="X-Provider-Event-Id", min_length=1, max_length=128),
) -> dict[str, str | bool]:
    """Accept a signed sandbox callback with durable event replay protection."""
    settings = get_settings()
    if provider != "sandbox":
        raise HTTPException(status_code=404, detail="provider webhook is not configured")
    if not settings.sandbox_webhook_secret:
        raise HTTPException(status_code=503, detail="sandbox webhook is not configured")

    raw_body = await request.body()
    try:
        verify_hmac_webhook(
            settings.sandbox_webhook_secret,
            signature,
            raw_body,
            tolerance_seconds=settings.webhook_tolerance_seconds,
        )
    except InvalidWebhookSignature as exc:
        raise HTTPException(status_code=401, detail="invalid webhook signature") from exc

    try:
        body = ProviderWebhookBody.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid webhook payload") from exc

    repository: PaymentRepository = request.app.state.repository
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    try:
        payment, created = await repository.apply_provider_webhook(
            provider,
            event_id,
            payload_hash,
            body.payment_id,
            body.status,
        )
    except WebhookReplayConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="payment not found") from exc
    except (InvalidPaymentTransition, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "accepted": True,
        "duplicate": not created,
        "payment_id": payment.id,
        "status": payment.status.value,
    }
