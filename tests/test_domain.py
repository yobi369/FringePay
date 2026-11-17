import pytest

from fringepay.domain import (
    InvalidPaymentTransition,
    Money,
    Payment,
    PaymentStatus,
)


def test_money_adds_minor_units_without_float_arithmetic() -> None:
    assert Money(125, "KES") + Money(75, "KES") == Money(200, "KES")


def test_money_rejects_mixed_currencies() -> None:
    with pytest.raises(ValueError, match="different currencies"):
        Money(100, "KES") + Money(100, "USD")


@pytest.mark.parametrize("currency", ["kes", "KE", "USDD", "123"])
def test_money_rejects_invalid_currency(currency: str) -> None:
    with pytest.raises(ValueError, match="three-letter"):
        Money(100, currency)


@pytest.mark.parametrize("amount", [True, 1.5, "100"])
def test_money_rejects_non_integer_amounts(amount: object) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        Money(amount, "KES")  # type: ignore[arg-type]


def test_payment_rejects_zero_amount() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        Payment("p1", Money(0, "KES"), "ref", "sandbox", None, PaymentStatus.PENDING)


def test_payment_can_transition_from_pending_to_processing() -> None:
    payment = Payment("p1", Money(100, "KES"), "ref", "sandbox", None, PaymentStatus.PENDING)
    updated = payment.transition_to(PaymentStatus.PROCESSING)
    assert updated.status is PaymentStatus.PROCESSING
    assert payment.status is PaymentStatus.PENDING


def test_payment_can_transition_from_processing_to_succeeded() -> None:
    payment = Payment("p1", Money(100, "KES"), "ref", "sandbox", None, PaymentStatus.PROCESSING)
    assert payment.transition_to(PaymentStatus.SUCCEEDED).status is PaymentStatus.SUCCEEDED


@pytest.mark.parametrize("terminal", [PaymentStatus.SUCCEEDED, PaymentStatus.FAILED, PaymentStatus.CANCELLED])
def test_terminal_payment_cannot_transition_again(terminal: PaymentStatus) -> None:
    payment = Payment("p1", Money(100, "KES"), "ref", "sandbox", None, terminal)
    with pytest.raises(InvalidPaymentTransition):
        payment.transition_to(PaymentStatus.PENDING)


def test_payment_cannot_skip_processing_backwards() -> None:
    payment = Payment("p1", Money(100, "KES"), "ref", "sandbox", None, PaymentStatus.PROCESSING)
    with pytest.raises(InvalidPaymentTransition):
        payment.transition_to(PaymentStatus.PENDING)
