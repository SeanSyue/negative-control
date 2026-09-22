"""A tiny shipping-fee rule, used to show what negative control does."""

FREE_SHIPPING_FROM = 100
SHIPPING_FEE = 8.0


def shipping_fee(total: float) -> float:
    """Orders of 100 or more ship free. Anything smaller pays a flat fee."""
    if total >= FREE_SHIPPING_FROM:
        return 0.0
    return SHIPPING_FEE
