from pricing import shipping_fee


def test_an_order_of_exactly_100_ships_free():
    # The boundary is where the rule is easiest to get wrong (>= vs >).
    assert shipping_fee(100) == 0.0


def test_small_order_has_a_fee():
    # This test passes. It also checks almost nothing: a fee of 0 is still
    # ">= 0". Negative control exposes it - see mutations/mutations_pricing.json
    # and the README.
    assert shipping_fee(50) >= 0
