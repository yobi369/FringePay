# Daraja sandbox integration

## Scope

FringePay's first provider adapter supports Safaricom Daraja STK Push in the sandbox environment only. The adapter creates the customer payment prompt and stores the returned CheckoutRequestID. It does not treat an HTTP acknowledgement as payment success.

Official portal: https://developer.safaricom.co.ke/

## Sandbox prerequisites

1. Register/sign in to the Daraja developer portal.
2. Create a sandbox application with the M-Pesa Express / STK Push product enabled.
3. Obtain the sandbox consumer key, consumer secret, shortcode, and Lipa Na M-Pesa passkey from the portal's sandbox app.
4. Deploy the FringePay callback endpoint on a publicly reachable HTTPS URL.
5. Configure the environment variables below in the API and worker deployments. Never commit actual credentials.

    FRINGEPAY_DEFAULT_PROVIDER=daraja
    FRINGEPAY_DARAJA_ENVIRONMENT=sandbox
    FRINGEPAY_DARAJA_CONSUMER_KEY=your-sandbox-consumer-key
    FRINGEPAY_DARAJA_CONSUMER_SECRET=your-sandbox-consumer-secret
    FRINGEPAY_DARAJA_SHORTCODE=174379
    FRINGEPAY_DARAJA_PASSKEY=your-sandbox-lipa-na-m-pesa-passkey
    FRINGEPAY_DARAJA_CALLBACK_URL=https://your-public-host/v1/webhooks/daraja?token=your-callback-secret
    FRINGEPAY_DARAJA_CALLBACK_SECRET=your-callback-secret
    FRINGEPAY_DARAJA_TRANSACTION_TYPE=CustomerPayBillOnline
    FRINGEPAY_PII_ENCRYPTION_KEY=<generated-fernet-key>

The shortcode shown is the common Daraja sandbox test shortcode; use the value assigned to your own sandbox app if different. Generate the PII encryption key with the cryptography Fernet helper shown in the root .env.example file and store it in a secret manager.

## Create an STK Push payment

The existing endpoint remains:

    POST /v1/payments

Headers:

    X-API-Key: <merchant-api-key>
    Idempotency-Key: <unique-order-key>

JSON body:

    {
      "amount_minor": 12500,
      "currency": "KES",
      "reference": "ORDER-001",
      "phone_number": "254712345678"
    }

For Daraja STK Push:
- phone_number must be in international Kenyan format: 2547XXXXXXXX or 2541XXXXXXXX.
- amount_minor is expressed in cents by FringePay, but STK Push accepts whole KES amounts. The amount must therefore be divisible by 100.
- The API returns HTTP 202 Accepted after the payment and dispatch event are durably reserved. This is not proof that Daraja accepted the request or that the customer paid.

The background worker performs OAuth authentication and submits the STK Push request. The returned CheckoutRequestID is stored as the provider reference.

## Callback and status verification

Daraja sends the result to the configured callback URL. FringePay treats the callback as a notification, not as trusted proof of payment:

1. Match the CheckoutRequestID to a previously created Daraja payment.
2. Query Daraja's STK Push status endpoint using authenticated provider credentials.
3. Only a definitive provider query result may transition the payment to succeeded, failed, or cancelled.
4. Duplicate verified events are idempotent.
5. The worker also polls unresolved Daraja checkouts periodically, so completion does not depend solely on callback delivery.

If the provider request times out after submission, FringePay cannot know whether Safaricom accepted it. The payment is moved to processing and its dispatch event is quarantined as unknown. It is not automatically resubmitted because that could create a second charge. Resolve it through status query/reconciliation before any manual retry.

## Current limitations

- Sandbox only; live Daraja endpoints are intentionally disabled.
- STK Push initiation and status-query verification are implemented; other Daraja products are not.
- Merchant portal, refund/reversal operations, M-Pesa receipt storage, and automated settlement statement ingestion are not yet part of this integration.
- Phone numbers are persisted for durable worker dispatch and encrypted at rest when FRINGEPAY_PII_ENCRYPTION_KEY is configured. Production startup requires this key. A retention/deletion policy, access controls, and managed key rotation are still required before handling real customer data.
- Do not use real customer funds or advertise live payment capability until provider approval, security review, operational controls, and legal/regulatory assessment are complete.

## Regulatory readiness

Safaricom's developer portal provides the integration environment; it does not by itself authorize FringePay to operate a payment service. Kenya's National Payment System Act and CBK authorisation framework must be assessed against the actual business model and data/payment flows. Obtain Kenyan legal/regulatory advice and confirm any applicable CBK requirements before offering the service commercially.

CBK reference: https://www.centralbank.go.ke/policy-procedures/legislation-and-guidelines/
