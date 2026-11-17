# ADR 0001: Provider adapter boundary

- **Status:** Accepted for the initial implementation
- **Date:** 2026-11-17

## Context

Application services should not depend directly on provider-specific SDKs, payloads, credentials, or status vocabularies. Provider behavior also differs in asynchronous confirmation, reversals, timeouts, and reconciliation.

## Decision

Define an internal provider contract and normalize provider responses into FringePay domain types. Begin with a deterministic sandbox adapter. Add real provider adapters only after their contracts, credentials, callback verification, and operational requirements are documented.

## Consequences

- Domain and API tests can run without external credentials or network access.
- Provider-specific behavior remains isolated behind adapters.
- Routing can be added without changing application-facing payment contracts.
- An adapter does not bypass provider approval, regulation, or settlement constraints.
