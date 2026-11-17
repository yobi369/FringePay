import pytest

from fringepay.domain import Money, Payment, PaymentStatus

def test_money_adds_minor_units_without_float_arithmetic() -> None:
    assert Money(125, "KES") + Money(75, "KES") == Money(200, "KES")

def test_money_rejects_mixed_currencies() -> None:
    with pytest.raises(ValueError, match="different currencies"):
        Money(100, "KES") + Money(100, "USD")

@pytest.mark.parametrize("currency", ["kes", "KE", "USDD", "123"])
def test_money_rejects_invalid_currency(currency: str) -> None:
    with pytest.raises(ValueError, match="three-letter"):
        Money(100, currency)

def test_money_rejects_boolean_amount() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Money(True, "KES")

def test_payment_rejects_zero_amount() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        Payment("p1", Money(0, "KES"), "ref", "sandbox", None, PaymentStatus.PENDING)
