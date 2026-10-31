from datetime import date
from decimal import Decimal as D

import pytest

from tests.conftest import Api, PW, login, make_active_sub


# ---------------- accounts ----------------
@pytest.mark.parametrize("pw,ok", [
    ("Short1!a", False),      # exactly 8: must be MORE than eight
    ("Longenough1!", True),
    ("alllowercase1!", False),
    ("ALLUPPERCASE1!", False),
    ("NoSpecialChar1", False),
    ("Valid-Pass9", True),
])
def test_password_rules(client, pw, ok):
    r = client.post("/api/auth/register", json={"email": "n@x.example.com", "name": "N", "password": pw})
    assert (r.status_code == 201) == ok, r.text


def test_email_is_unique_regardless_of_case(client):
    body = {"email": "Dup@X.example.com", "name": "A", "password": PW}
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/register", json={**body, "email": "dup@x.EXAMPLE.com"}).status_code == 409


def test_roles_are_enforced(client, admin, staff, catalog):
    reg = client.post("/api/auth/register", json={"email": "c@x.example.com", "name": "C", "password": PW}).json()
    cust = Api(client, reg["access_token"])
    assert reg["user"]["role"] == "customer"
    # only the admin changes the catalogue or adds staff
    assert cust.post("/products", {"name": "x", "sales_price": "1"}).status_code == 403
    assert staff.post("/products", {"name": "x", "sales_price": "1"}).status_code == 403
    assert staff.post("/users/staff", {"email": "s2@x.example.com", "name": "S2", "password": PW}).status_code == 403
    assert admin.post("/users/staff", {"email": "s2@x.example.com", "name": "S2", "password": PW}).status_code == 201
    # customers cannot reach back-office data; staff cannot create discounts
    assert cust.get("/customers").status_code == 403
    assert cust.get("/reports/summary").status_code == 403
    assert staff.post("/discounts", {"name": "d", "kind": "fixed", "value": "1", "scope": "subscription"}).status_code == 403
    assert client.get("/api/subscriptions").status_code == 401


def test_customer_only_sees_their_own_subscriptions_and_invoices(client, admin, staff, catalog):
    sid = make_active_sub(staff, catalog)          # belongs to Acme, not to the signed-up customer
    staff.post("/billing/run", {"auto_confirm": True})
    reg = client.post("/api/auth/register", json={"email": "other@x.example.com", "name": "Other", "password": PW}).json()
    other = Api(client, reg["access_token"])
    assert other.get("/subscriptions").json()["total"] == 0
    assert other.get(f"/subscriptions/{sid}").status_code == 404
    assert other.get("/invoices").json()["total"] == 0
    assert other.get("/invoices/1").status_code == 404


def test_password_reset_flow(client, admin):
    r = client.post("/api/auth/forgot-password", json={"email": "nobody@x.example.com"})
    assert r.status_code == 200 and client.get("/api/dev/mails").json() == []   # no leak, no mail
    client.post("/api/auth/forgot-password", json={"email": "admin@t.example.com"})
    mail = client.get("/api/dev/mails").json()[0]
    assert mail["to"] == "admin@t.example.com"
    token = mail["body"].split("token=")[1].split()[0]
    assert client.post("/api/auth/reset-password", json={"token": token, "password": "weak"}).status_code == 422
    assert client.post("/api/auth/reset-password", json={"token": token, "password": "BrandNew#Pass1"}).status_code == 200
    assert client.post("/api/auth/reset-password", json={"token": token, "password": "BrandNew#Pass2"}).status_code == 400
    login(client, "admin@t.example.com", "BrandNew#Pass1")
    assert client.post("/api/auth/login", json={"email": "admin@t.example.com", "password": PW}).status_code == 401


def test_registering_claims_a_customer_staff_already_created(client, staff, catalog):
    sid = make_active_sub(staff, catalog)
    reg = client.post("/api/auth/register", json={"email": "ACME@x.example.com", "name": "Acme Owner", "password": PW}).json()
    assert reg["user"]["customer_id"] == catalog["cust"]["id"]
    assert Api(client, reg["access_token"]).get(f"/subscriptions/{sid}").status_code == 200


# ---------------- catalogue ----------------
def test_variant_adds_to_price_and_plan_minimum_quantity(staff, catalog):
    r = staff.post("/subscriptions", {"customer_id": catalog["cust"]["id"], "plan_id": catalog["plan"]["id"],
                                      "lines": [{"product_id": catalog["prod"]["id"], "variant_id": catalog["odoo"], "quantity": 2}]})
    assert r.status_code == 201
    line = r.json()["lines"][0]
    assert D(line["unit_price"]) == D("1560.00")                       # 1000 + 560 for the Odoo brand
    assert D(line["net"]) == D("3120.00") and D(line["tax"]) == D("312.00")
    bad = staff.post("/subscriptions", {"customer_id": catalog["cust"]["id"], "plan_id": catalog["plan"]["id"],
                                        "lines": [{"product_id": catalog["prod"]["id"], "variant_id": catalog["odoo"], "quantity": 1}]})
    assert bad.status_code == 422 and "at least 2" in bad.json()["detail"]
    novar = staff.post("/subscriptions", {"customer_id": catalog["cust"]["id"], "plan_id": catalog["plan"]["id"],
                                          "lines": [{"product_id": catalog["prod"]["id"], "quantity": 2}]})
    assert novar.status_code == 422


def test_plan_availability_window(admin, staff, catalog):
    p = admin.post("/plans", {"name": "Sale", "price": "0", "interval": "monthly", "valid_from": "2025-03-01"}).json()
    r = staff.post("/subscriptions", {"customer_id": catalog["cust"]["id"], "plan_id": p["id"], "start_date": "2025-01-20",
                                      "lines": [{"product_id": catalog["prod"]["id"], "variant_id": catalog["plain"], "quantity": 1}]})
    assert r.status_code == 422 and "available from" in r.json()["detail"]


def test_quotation_from_template(admin, staff, catalog, clock):
    t = admin.post("/templates", {"name": "Std", "validity_days": 10, "plan_id": catalog["plan"]["id"],
                                  "lines": [{"product_id": catalog["prod"]["id"], "variant_id": catalog["plain"], "quantity": 3}]}).json()
    s = staff.post("/subscriptions", {"customer_id": catalog["cust"]["id"], "template_id": t["id"]}).json()
    assert s["status"] == "quotation" and s["number"].startswith("SUB-")
    assert s["quote_valid_until"] == "2025-01-25" and s["lines"][0]["quantity"] == 3
    clock.d = date(2025, 2, 1)   # quote lapsed: it can no longer be confirmed
    assert "confirm" not in staff.get(f"/subscriptions/{s['id']}").json()["allowed_actions"]
    assert staff.post(f"/subscriptions/{s['id']}/transition", {"action": "confirm"}).status_code == 409


def test_lifecycle_order_is_enforced(staff, catalog):
    s = staff.post("/subscriptions", {"customer_id": catalog["cust"]["id"], "plan_id": catalog["plan"]["id"],
                                      "lines": [{"product_id": catalog["prod"]["id"], "variant_id": catalog["plain"], "quantity": 2}]}).json()
    assert s["status"] == "draft"
    assert staff.post(f"/subscriptions/{s['id']}/transition", {"action": "activate"}).status_code == 409
    assert staff.post(f"/subscriptions/{s['id']}/transition", {"action": "confirm"}).status_code == 409


# ---------------- billing ----------------
def test_billing_is_idempotent_and_catches_up_without_gaps(staff, catalog, clock):
    sid = make_active_sub(staff, catalog, start="2025-01-01")
    clock.d = date(2025, 3, 20)    # Jan, Feb and Mar periods are all due
    r1 = staff.post("/billing/run", {"auto_confirm": True}).json()
    assert r1["invoices_created"] == 3 and r1["errors"] == []
    r2 = staff.post("/billing/run", {"auto_confirm": True}).json()
    assert r2["invoices_created"] == 0
    invs = staff.get(f"/invoices?subscription_id={sid}&page_size=50").json()["items"]
    assert sorted(i["period_start"] for i in invs) == ["2025-01-01", "2025-02-01", "2025-03-01"]
    assert all(i["status"] == "confirmed" for i in invs)
    clock.d = date(2025, 4, 1)
    assert staff.post("/billing/run", {}).json()["invoices_created"] == 1
    assert staff.get(f"/subscriptions/{sid}").json()["next_billing_date"] == "2025-05-01"


def test_invoice_content_matches_subscription(staff, catalog, clock):
    make_active_sub(staff, catalog, qty=2)
    clock.d = date(2025, 1, 1)
    staff.post("/billing/run", {})
    inv = staff.get("/invoices/1").json()
    # plan fee 100 + 2 x 1000 CRM, 10% tax on the product line only (plan has no tax)
    assert D(inv["subtotal"]) == D("2100.00") and D(inv["tax_total"]) == D("200.00") and D(inv["total"]) == D("2300.00")
    assert inv["status"] == "draft" and inv["due_date"] == "2025-01-16" and inv["customer_name"] == "Acme"
    assert [l["description"] for l in inv["lines"]][0].startswith("Monthly plan")


def test_billing_stops_at_expiry_and_auto_close_plan_closes(admin, staff, catalog, clock):
    plan = admin.post("/plans", {"name": "Pilot", "price": "10", "interval": "weekly", "auto_close": True}).json()
    sid = make_active_sub(staff, catalog, qty=1, start="2025-01-01", expiry="2025-01-22", plan=plan)
    clock.d = date(2025, 2, 15)
    r = staff.post("/billing/run", {}).json()
    assert r["invoices_created"] == 3 and r["closed"] == 1     # weeks starting Jan 1, 8, 15; Jan 22 is outside the term
    assert staff.get(f"/subscriptions/{sid}").json()["status"] == "closed"


def test_paused_time_is_not_billed_and_extends_the_term(staff, catalog, clock):
    sid = make_active_sub(staff, catalog, start="2025-01-01", expiry="2025-12-31")
    clock.d = date(2025, 1, 1)
    staff.post("/billing/run", {})
    clock.d = date(2025, 1, 10)
    staff.post(f"/subscriptions/{sid}/transition", {"action": "pause"})
    clock.d = date(2025, 2, 20)                                  # paused 41 days
    assert staff.post("/billing/run", {}).json()["invoices_created"] == 0
    s = staff.post(f"/subscriptions/{sid}/transition", {"action": "resume"}).json()
    assert s["status"] == "active" and s["expiry_date"] == "2026-02-10" and s["next_billing_date"] == "2025-03-14"   # 22 paid days were left at pause: Feb 20 + 22


def test_plan_flags_gate_actions(admin, staff, catalog):
    plan = admin.post("/plans", {"name": "Locked", "price": "0", "interval": "monthly", "closable": False,
                                 "pausable": False, "renewable": False}).json()
    sid = make_active_sub(staff, catalog, qty=1, plan=plan)
    allowed = staff.get(f"/subscriptions/{sid}").json()["allowed_actions"]
    assert allowed == []
    for a in ("close", "pause", "renew"):
        assert staff.post(f"/subscriptions/{sid}/transition", {"action": a}).status_code == 409


def test_renew_extends_by_one_term(staff, catalog):
    sid = make_active_sub(staff, catalog, start="2025-01-01", expiry="2026-01-01")
    s = staff.post(f"/subscriptions/{sid}/transition", {"action": "renew"}).json()
    assert s["expiry_date"] == "2027-01-01"


# ---------------- discounts ----------------
def test_discount_applies_automatically_and_respects_usage_limit(admin, staff, catalog, clock):
    admin.post("/discounts", {"name": "10% seats", "kind": "percent", "value": "10", "scope": "product",
                              "product_ids": [catalog["prod"]["id"]], "min_quantity": 2, "usage_limit": 1})
    a = make_active_sub(staff, catalog, qty=2)
    b = make_active_sub(staff, catalog, qty=2)
    clock.d = date(2025, 1, 1)
    staff.post("/billing/run", {})
    ia = staff.get(f"/invoices?subscription_id={a}").json()["items"][0]["id"]
    ib = staff.get(f"/invoices?subscription_id={b}").json()["items"][0]["id"]
    da, db_ = staff.get(f"/invoices/{ia}").json(), staff.get(f"/invoices/{ib}").json()
    assert D(da["discount_total"]) == D("200.00") and D(da["total"]) == D("2080.00")   # (2000-200)*1.1 + 100 plan fee
    assert D(db_["discount_total"]) == 0                                                # limit of 1 already spent
    assert staff.get("/discounts").json()[0]["used_count"] == 1


def test_discount_stops_after_it_expires(admin, staff, catalog, clock):
    admin.post("/discounts", {"name": "Jan only", "kind": "fixed", "value": "100", "scope": "subscription",
                              "end_date": "2025-01-31"})
    sid = make_active_sub(staff, catalog)
    clock.d = date(2025, 2, 5)
    staff.post("/billing/run", {})
    items = staff.get(f"/invoices?subscription_id={sid}&page_size=10").json()["items"]
    assert len(items) == 2
    assert all(D(staff.get(f"/invoices/{i['id']}").json()["discount_total"]) == 0 for i in items)


def test_cancelling_an_invoice_returns_the_discount_use(admin, staff, catalog, clock):
    admin.post("/discounts", {"name": "Once", "kind": "fixed", "value": "50", "scope": "subscription", "usage_limit": 1})
    make_active_sub(staff, catalog)
    clock.d = date(2025, 1, 1)
    staff.post("/billing/run", {})
    assert staff.get("/discounts").json()[0]["used_count"] == 1
    assert staff.post("/invoices/1/cancel").status_code == 200
    assert staff.get("/discounts").json()[0]["used_count"] == 0


# ---------------- invoices & payments ----------------
def _billed_invoice(staff, catalog, clock):
    make_active_sub(staff, catalog)
    clock.d = date(2025, 1, 1)
    staff.post("/billing/run", {"auto_confirm": True})
    return staff.get("/invoices/1").json()


def test_payments_partial_then_full_and_overpayment_rejected(staff, catalog, clock):
    inv = _billed_invoice(staff, catalog, clock)
    total = D(inv["total"])
    assert staff.post("/invoices/1/payments", {"method": "cash", "amount": str(total + 1)}).status_code == 422
    r = staff.post("/invoices/1/payments", {"method": "card", "amount": "500", "note": "deposit"})
    assert r.status_code == 201 and r.json()["status"] == "confirmed" and D(r.json()["balance"]) == total - 500
    r = staff.post("/invoices/1/payments", {"method": "bank_transfer", "amount": str(total - 500)})
    assert r.json()["status"] == "paid" and D(r.json()["balance"]) == 0 and len(r.json()["payments"]) == 2
    assert staff.post("/invoices/1/payments", {"method": "cash", "amount": "1"}).status_code == 409
    assert staff.post("/invoices/1/cancel").status_code == 409


def test_cannot_pay_a_draft_and_future_dates_rejected(staff, catalog, clock):
    make_active_sub(staff, catalog)
    clock.d = date(2025, 1, 1)
    staff.post("/billing/run", {})                      # left as draft
    assert staff.post("/invoices/1/payments", {"method": "cash", "amount": "5"}).status_code == 409
    staff.post("/invoices/1/confirm")
    assert staff.post("/invoices/1/payments", {"method": "cash", "amount": "5", "paid_on": "2025-02-01"}).status_code == 422


def test_overdue_is_derived_from_due_date_and_balance(staff, catalog, clock):
    _billed_invoice(staff, catalog, clock)               # due 2025-01-16
    assert staff.get("/invoices?status=overdue").json()["total"] == 0
    clock.d = date(2025, 1, 20)
    od = staff.get("/invoices?status=overdue").json()
    assert od["total"] == 1 and od["items"][0]["days_overdue"] == 4
    assert staff.get("/reports/summary").json()["overdue_count"] == 1
    total = staff.get("/invoices/1").json()["total"]
    staff.post("/invoices/1/payments", {"method": "upi", "amount": total})
    assert staff.get("/invoices?status=overdue").json()["total"] == 0


def test_cancel_with_rebill_rewinds_only_the_latest_period(staff, catalog, clock):
    sid = make_active_sub(staff, catalog)
    clock.d = date(2025, 2, 10)
    staff.post("/billing/run", {})                      # invoices 1 (Jan) and 2 (Feb)
    assert staff.post("/invoices/1/cancel?rebill=true").status_code == 409   # January is not the latest
    assert staff.post("/invoices/2/cancel?rebill=true").status_code == 200
    assert staff.post("/billing/run", {}).json()["invoices_created"] == 1
    periods = sorted(i["period_start"] for i in staff.get(f"/invoices?subscription_id={sid}&page_size=10").json()["items"]
                     if i["status"] != "cancelled")
    assert periods == ["2025-01-01", "2025-02-01"]


def test_send_invoice_logs_mail_and_marks_sent(staff, catalog, clock, client):
    _billed_invoice(staff, catalog, clock)
    r = staff.post("/invoices/1/send")
    assert r.status_code == 200 and r.json()["sent_at"]
    assert client.get("/api/dev/mails").json()[0]["to"] == "acme@x.example.com"


def test_customer_portal_sees_issued_invoices_only(client, staff, catalog, clock):
    make_active_sub(staff, catalog)
    reg = client.post("/api/auth/register", json={"email": "acme@x.example.com", "name": "Acme", "password": PW}).json()
    me = Api(client, reg["access_token"])
    clock.d = date(2025, 1, 1)
    staff.post("/billing/run", {})                      # draft: hidden from the customer
    assert me.get("/invoices").json()["total"] == 0
    staff.post("/invoices/1/confirm")
    assert me.get("/invoices").json()["total"] == 1
    assert me.post("/invoices/1/confirm").status_code == 403


def test_reports_summary(staff, catalog, clock):
    _billed_invoice(staff, catalog, clock)
    total = D(staff.get("/invoices/1").json()["total"])
    staff.post("/invoices/1/payments", {"method": "card", "amount": "1000"})
    s = staff.get("/reports/summary?date_from=2025-01-01&date_to=2025-01-31").json()
    assert s["active_subscriptions"] == 1
    assert D(s["mrr"]) == D("2100.00")                  # plan fee + 2 x 1000, monthly
    assert D(s["collected_in_range"]) == D("1000.00")
    assert D(s["outstanding_amount"]) == total - 1000 and s["outstanding_count"] == 1


def test_customers_cannot_choose_their_own_payment_terms(client, catalog):
    reg = client.post("/api/auth/register", json={"email": "self@x.example.com", "name": "Self", "password": PW}).json()
    me = Api(client, reg["access_token"])
    r = me.post("/subscriptions", {"plan_id": catalog["plan"]["id"], "payment_term_id": catalog["term"]["id"],
                                   "lines": [{"product_id": catalog["prod"]["id"], "variant_id": catalog["plain"],
                                              "quantity": 2, "unit_price": "1.00"}]})
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["status"] == "quotation" and s["payment_term"] is None       # their term request was ignored
    assert D(s["lines"][0]["unit_price"]) == D("1000.00")                  # and so was their own price
    assert me.post("/subscriptions", {"customer_id": catalog["cust"]["id"], "plan_id": catalog["plan"]["id"],
                                      "lines": [{"product_id": catalog["prod"]["id"], "variant_id": catalog["plain"], "quantity": 2}]}
                   ).json()["customer_id"] == reg["user"]["customer_id"]     # cannot bill someone else
