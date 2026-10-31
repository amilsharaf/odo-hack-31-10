"""Pure pricing engine: lines + eligible discount rules in, priced lines out. No database here,
so every rounding and stacking rule can be tested directly.

Rules (kept deliberately simple and predictable):
  * Product discounts apply per line; if several qualify the one worth most is used (no stacking
    between product discounts).
  * A subscription discount then applies to what is left of the whole invoice, spread over the
    lines in proportion to their remaining value, so tax is computed on the discounted amount.
  * A fixed amount is taken once per line (product scope) or once per invoice (subscription
    scope), and can never push a line below zero.
  * Tax is computed per line on the discounted net and rounded per line.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def q(x: Decimal) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class LineIn:
    description: str
    quantity: int
    unit_price: Decimal
    tax_rate: Decimal = Decimal(0)
    product_id: int | None = None  # None = plan fee, not eligible for product discounts


@dataclass
class Rule:
    id: int
    name: str
    kind: str  # fixed | percent
    value: Decimal
    scope: str  # product | subscription
    min_purchase: Decimal = Decimal(0)
    min_quantity: int = 0
    product_ids: frozenset[int] = frozenset()


@dataclass
class LineOut:
    src: LineIn
    gross: Decimal
    discount: Decimal = ZERO
    discount_id: int | None = None
    tax: Decimal = ZERO
    total: Decimal = ZERO


@dataclass
class Priced:
    lines: list[LineOut]
    used: set[int] = field(default_factory=set)
    subtotal: Decimal = ZERO
    discount_total: Decimal = ZERO
    tax_total: Decimal = ZERO
    total: Decimal = ZERO


def _amount(rule: Rule, base: Decimal) -> Decimal:
    raw = base * rule.value / 100 if rule.kind == "percent" else rule.value
    return min(q(raw), base)


def price(lines: list[LineIn], rules: list[Rule]) -> Priced:
    out = [LineOut(src=l, gross=q(l.unit_price * l.quantity)) for l in lines]
    used: set[int] = set()

    for lo in out:
        pid = lo.src.product_id
        if pid is None or lo.gross <= 0:
            continue
        best: tuple[Decimal, Rule] | None = None
        for r in rules:
            if r.scope != "product" or pid not in r.product_ids:
                continue
            if lo.src.quantity < r.min_quantity or lo.gross < r.min_purchase:
                continue
            amt = _amount(r, lo.gross)
            if amt > 0 and (best is None or amt > best[0]):
                best = (amt, r)
        if best:
            lo.discount, lo.discount_id = best[0], best[1].id
            used.add(best[1].id)

    base = sum((lo.gross - lo.discount for lo in out), ZERO)
    qty = sum(lo.src.quantity for lo in out if lo.src.product_id is not None)
    best = None
    for r in rules:
        if r.scope != "subscription" or base <= 0:
            continue
        if qty < r.min_quantity or base < r.min_purchase:
            continue
        amt = _amount(r, base)
        if amt > 0 and (best is None or amt > best[0]):
            best = (amt, r)
    if best:
        amt, rule = best
        used.add(rule.id)
        live = [lo for lo in out if lo.gross - lo.discount > 0]
        left = amt
        for i, lo in enumerate(live):
            net = lo.gross - lo.discount
            share = left if i == len(live) - 1 else min(q(amt * net / base), left)
            lo.discount += share
            left -= share
            if lo.discount_id is None:
                lo.discount_id = rule.id

    res = Priced(lines=out, used=used)
    for lo in out:
        net = lo.gross - lo.discount
        lo.tax = q(net * lo.src.tax_rate / 100)
        lo.total = net + lo.tax
        res.subtotal += lo.gross
        res.discount_total += lo.discount
        res.tax_total += lo.tax
        res.total += lo.total
    return res
