# Sandbox boundary

FringePay currently runs a deterministic **sandbox adapter only**. It does not connect to
Safaricom Daraja, Airtel Money, a bank, a card network, or any other live payment rail.

The initial payment service stores payment and idempotency records in process memory. This is
intentionally suitable only for local development and tests: records disappear on restart,
multiple workers do not share state, and concurrent requests are not protected by a durable
unique constraint. Do not use this implementation for real transactions.

Amounts are represented as integer minor units plus a three-letter uppercase currency code.
For Kenya shillings, callers should send the amount in cents (for example, KSh 10.50 is 1050
minor units). The API never accepts floating-point monetary values.

A sandbox success result is a simulated provider response. It is not evidence of settlement,
a bank credit, or a movement of customer funds. Production use requires durable persistence,
transactional idempotency, authenticated tenants, authorization, provider contracts and
credentials, signed callback verification, reconciliation, security review, and applicable
regulatory/legal review.
