"""Safaricom Daraja STK Push adapter (sandbox only).

This adapter initiates a customer prompt. An HTTP acknowledgement is not proof
that the customer paid; final status must be verified through the callback/query flow.
"""

from __future__ import annotations

import base64
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from fringepay.config import Settings
from fringepay.domain import PaymentStatus
from fringepay.providers import (
    PaymentCommand,
    ProviderOutcomeUnknown,
    ProviderRejected,
    ProviderResult,
    ProviderTemporaryError,
)


class DarajaProvider:
    """Daraja STK Push adapter restricted to Safaricom's sandbox environment."""

    name = "daraja"
    SANDBOX_BASE_URL = "https://sandbox.safaricom.co.ke"

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if settings.daraja_environment != "sandbox":
            raise ValueError("Daraja live environment is disabled in this release")
        required = {
            "consumer key": settings.daraja_consumer_key,
            "consumer secret": settings.daraja_consumer_secret,
            "business shortcode": settings.daraja_shortcode,
            "Lipa Na M-Pesa passkey": settings.daraja_passkey,
            "callback URL": settings.daraja_callback_url,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"missing Daraja configuration: {', '.join(missing)}")
        if not settings.daraja_callback_url.startswith("https://"):
            raise ValueError("Daraja callback URL must use HTTPS")
        if settings.daraja_transaction_type not in {
            "CustomerPayBillOnline",
            "CustomerBuyGoodsOnline",
        }:
            raise ValueError("unsupported Daraja STK transaction type")

        self.settings = settings
        self._client = http_client or httpx.AsyncClient(
            base_url=self.SANDBOX_BASE_URL,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )
        self._owns_client = http_client is None
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get_access_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        try:
            response = await self._client.get(
                "/oauth/v1/generate",
                params={"grant_type": "client_credentials"},
                auth=(
                    self.settings.daraja_consumer_key,
                    self.settings.daraja_consumer_secret,
                ),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderTemporaryError("Daraja authentication is temporarily unavailable") from exc

        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ProviderTemporaryError("Daraja returned an invalid access token response")
        try:
            expires_in = int(payload.get("expires_in", "3599"))
        except (TypeError, ValueError):
            expires_in = 3599
        self._access_token = token
        self._token_expires_at = time.monotonic() + max(30, expires_in - 60)
        return token

    async def query_stk_status(self, checkout_request_id: str) -> PaymentStatus | None:
        """Query Safaricom for final status; callback payloads alone are not trusted."""
        token = await self._get_access_token()
        timestamp = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")
        shortcode = self.settings.daraja_shortcode
        password_source = f"{shortcode}{self.settings.daraja_passkey}{timestamp}"
        password = base64.b64encode(password_source.encode("utf-8")).decode("ascii")
        payload = {
            "BusinessShortCode": shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        }
        try:
            response = await self._client.post(
                "/mpesa/stkpushquery/v1/query",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderTemporaryError("Daraja transaction status query is unavailable") from exc

        result_code = result.get("ResultCode")
        if result_code is None:
            return None
        if str(result_code) == "0":
            return PaymentStatus.SUCCEEDED
        if str(result_code) == "1032":
            return PaymentStatus.CANCELLED
        return PaymentStatus.FAILED

    async def initiate(self, command: PaymentCommand) -> ProviderResult:
        if command.amount.currency != "KES":
            raise ProviderRejected("Daraja STK Push currently supports KES only")
        if command.amount.minor_units % 100:
            raise ProviderRejected("Daraja STK Push requires whole KES amounts")
        if not command.phone_number or not (
            len(command.phone_number) == 12
            and command.phone_number.startswith(("2547", "2541"))
            and command.phone_number.isdigit()
        ):
            raise ProviderRejected("a valid Kenyan M-Pesa phone number is required")

        token = await self._get_access_token()
        timestamp = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")
        shortcode = self.settings.daraja_shortcode
        password_source = f"{shortcode}{self.settings.daraja_passkey}{timestamp}"
        password = base64.b64encode(password_source.encode("utf-8")).decode("ascii")
        payload = {
            "BusinessShortCode": shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": self.settings.daraja_transaction_type,
            "Amount": command.amount.minor_units // 100,
            "PartyA": command.phone_number,
            "PartyB": shortcode,
            "PhoneNumber": command.phone_number,
            "CallBackURL": self.settings.daraja_callback_url,
            "AccountReference": command.payment_id[:12],
            "TransactionDesc": "FringePay",
        }

        try:
            response = await self._client.post(
                "/mpesa/stkpush/v1/processrequest",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            # The request may have reached Safaricom. Never automatically retry a
            # potentially accepted charge: reconciliation/query must resolve it.
            raise ProviderOutcomeUnknown("Daraja STK Push outcome is unknown") from exc

        if response.status_code >= 500:
            raise ProviderOutcomeUnknown("Daraja STK Push outcome is unknown")
        if response.status_code >= 400:
            raise ProviderRejected("Daraja rejected the STK Push request")

        try:
            result = response.json()
        except ValueError as exc:
            raise ProviderOutcomeUnknown("Daraja returned an unreadable STK Push response") from exc

        if str(result.get("ResponseCode")) != "0":
            raise ProviderRejected("Daraja did not accept the STK Push request")
        checkout_request_id = result.get("CheckoutRequestID")
        if not isinstance(checkout_request_id, str) or not checkout_request_id:
            raise ProviderOutcomeUnknown("Daraja acknowledgement did not include a checkout ID")

        return ProviderResult(
            provider=self.name,
            provider_reference=checkout_request_id,
            status=PaymentStatus.PENDING,
        )
