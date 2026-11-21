import base64
import json

import httpx
import pytest

from fringepay.config import Settings
from fringepay.daraja import DarajaProvider
from fringepay.domain import Money, PaymentStatus
from fringepay.providers import (
    PaymentCommand,
    ProviderOutcomeUnknown,
    ProviderRejected,
    ProviderTemporaryError,
)

BASE_URL = DarajaProvider.SANDBOX_BASE_URL


def make_settings(**overrides) -> Settings:
    values = {
        "daraja_environment": "sandbox",
        "daraja_consumer_key": "sandbox-consumer-key",
        "daraja_consumer_secret": "sandbox-consumer-secret",
        "daraja_shortcode": "174379",
        "daraja_passkey": "sandbox-passkey",
        "daraja_callback_url": "https://payments.example.test/v1/webhooks/daraja",
        "daraja_transaction_type": "CustomerPayBillOnline",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_daraja_stk_push_uses_oauth_and_returns_pending_acknowledgement() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/oauth/v1/generate":
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": "3599"})
        assert request.url.path == "/mpesa/stkpush/v1/processrequest"
        assert request.headers["Authorization"] == "Bearer test-token"
        payload = json.loads(request.content)
        assert payload["Amount"] == 125
        assert payload["PartyA"] == "254712345678"
        assert payload["AccountReference"] == "payment-id-1"
        assert payload["TransactionType"] == "CustomerPayBillOnline"
        password_source = base64.b64decode(payload["Password"]).decode()
        assert password_source.startswith("174379sandbox-passkey")
        return httpx.Response(
            200,
            json={
                "ResponseCode": "0",
                "MerchantRequestID": "merchant-request-1",
                "CheckoutRequestID": "ws_CO_123",
                "ResponseDescription": "Success. Request accepted for processing",
            },
        )

    async with httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        provider = DarajaProvider(make_settings(), http_client=client)
        result = await provider.initiate(
            PaymentCommand(
                payment_id="payment-id-123456",
                amount=Money(12500, "KES"),
                reference="order-125",
                phone_number="254712345678",
            )
        )

    assert len(seen) == 2
    assert result.provider == "daraja"
    assert result.provider_reference == "ws_CO_123"
    assert result.status is PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_daraja_rejects_sub_shilling_amounts_and_non_kes() -> None:
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    ) as client:
        provider = DarajaProvider(make_settings(), http_client=client)
        with pytest.raises(ProviderRejected, match="whole KES"):
            await provider.initiate(
                PaymentCommand("payment-1", Money(1050, "KES"), "order", "254712345678")
            )
        with pytest.raises(ProviderRejected, match="KES only"):
            await provider.initiate(
                PaymentCommand("payment-2", Money(10000, "USD"), "order", "254712345678")
            )


@pytest.mark.asyncio
async def test_daraja_quarantines_ambiguous_stk_push_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v1/generate":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": "3599"})
        raise httpx.ReadTimeout("response timed out", request=request)

    async with httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        provider = DarajaProvider(make_settings(), http_client=client)
        with pytest.raises(ProviderOutcomeUnknown):
            await provider.initiate(
                PaymentCommand("payment-1", Money(10000, "KES"), "order", "254712345678")
            )


@pytest.mark.asyncio
async def test_daraja_authentication_failure_is_safe_to_retry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "temporarily unavailable"})

    async with httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        provider = DarajaProvider(make_settings(), http_client=client)
        with pytest.raises(ProviderTemporaryError):
            await provider.initiate(
                PaymentCommand("payment-1", Money(10000, "KES"), "order", "254712345678")
            )


def test_daraja_live_environment_is_disabled() -> None:
    with pytest.raises(ValueError, match="live environment is disabled"):
        DarajaProvider(make_settings(daraja_environment="production"))


def test_daraja_requires_https_callback_url() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        DarajaProvider(make_settings(daraja_callback_url="http://localhost/callback"))


@pytest.mark.asyncio
async def test_daraja_status_query_maps_final_result_codes() -> None:
    responses = [
        {"access_token": "test-token", "expires_in": "3599"},
        {
            "ResponseCode": "0",
            "CheckoutRequestID": "checkout-verified-001",
            "ResultCode": "0",
            "ResultDesc": "The service request is processed successfully",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v1/generate":
            return httpx.Response(200, json=responses[0])
        assert request.url.path == "/mpesa/stkpushquery/v1/query"
        assert request.headers["Authorization"] == "Bearer test-token"
        payload = json.loads(request.content)
        assert payload["CheckoutRequestID"] == "checkout-verified-001"
        return httpx.Response(200, json=responses[1])

    async with httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        provider = DarajaProvider(make_settings(), http_client=client)
        status = await provider.query_stk_status("checkout-verified-001")

    assert status is PaymentStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_daraja_status_query_keeps_unresolved_result_pending() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v1/generate":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": "3599"})
        return httpx.Response(
            200,
            json={
                "ResponseCode": "0",
                "ResponseDescription": "The service request has been accepted successfully",
            },
        )

    async with httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        provider = DarajaProvider(make_settings(), http_client=client)
        status = await provider.query_stk_status("checkout-still-pending")

    assert status is None
