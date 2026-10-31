from decimal import Decimal as D

from app.services.pricing import LineIn, Rule, price
from app.services.dates import advance
from datetime import date


def L(pid, qty, unit, tax=0): return LineIn(f"p{pid}", qty, D(unit), D(tax), pid)


def test_tax_and_rounding():
    r = price([L(1, 3, "33.33", "18")], [])
    assert r.subtotal == D("99.99") and r.tax_total == D("18.00") and r.total == D("117.99")


def test_percent_product_discount_needs_min_quantity():
    rule = Rule(1, "d", "percent", D(10), "product", min_quantity=5, product_ids=frozenset({1}))
    assert price([L(1, 4, "100")], [rule]).discount_total == 0
    r = price([L(1, 5, "100")], [rule])
    assert r.discount_total == D("50.00") and r.total == D("450.00") and r.used == {1}


def test_fixed_discount_never_goes_below_zero():
    rule = Rule(1, "d", "fixed", D(500), "product", product_ids=frozenset({1}))
    r = price([L(1, 1, "120")], [rule])
    assert r.total == D("0.00") and r.discount_total == D("120.00")


def test_best_product_discount_wins_without_stacking():
    a = Rule(1, "a", "percent", D(10), "product", product_ids=frozenset({1}))
    b = Rule(2, "b", "fixed", D(30), "product", product_ids=frozenset({1}))
    r = price([L(1, 1, "100")], [a, b])
    assert r.discount_total == D("30.00") and r.used == {2}


def test_subscription_discount_is_spread_and_taxed_after_discount():
    rule = Rule(1, "sub", "fixed", D(10), "subscription")
    r = price([L(1, 1, "100", "10"), L(2, 1, "50", "0"), L(None, 1, "50", "0")], [rule])
    assert sum(l.discount for l in r.lines) == D("10.00")      # allocation sums exactly, no lost cents
    assert r.total == D("200.00") - D("10.00") + r.tax_total
    assert r.lines[0].tax == ((D("100") - r.lines[0].discount) * D("0.10")).quantize(D("0.01"))


def test_spread_rounding_remainder_lands_on_last_line():
    rule = Rule(1, "sub", "fixed", D("0.10"), "subscription")
    r = price([L(1, 1, "10"), L(2, 1, "10"), L(3, 1, "10")], [rule])
    assert sum(l.discount for l in r.lines) == D("0.10")


def test_plan_fee_not_hit_by_product_discount_but_by_subscription_one():
    p = Rule(1, "p", "percent", D(50), "product", product_ids=frozenset({1}))
    r = price([L(None, 1, "100"), L(1, 1, "100")], [p])
    assert r.lines[0].discount == 0 and r.lines[1].discount == D("50.00")


def test_month_end_anchor_does_not_drift():
    a = date(2025, 1, 31)
    assert [advance(a, "monthly", n) for n in range(4)] == [
        date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31), date(2025, 4, 30)]
