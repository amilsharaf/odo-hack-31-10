import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DEV_MAILBOX"] = "true"

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import deps  # noqa: E402
from app import models as m  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402

PW = "Passw0rd!x"


class Clock:
    d = date(2025, 1, 15)


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    m.Base.metadata.drop_all(engine)
    m.Base.metadata.create_all(engine)
    Clock.d = date(2025, 1, 15)
    monkeypatch.setattr(deps, "today", lambda: Clock.d)
    with SessionLocal() as db:
        db.add(m.User(email="admin@t.example.com", name="Admin", password_hash=hash_password(PW), role=m.ADMIN))
        db.add(m.User(email="staff@t.example.com", name="Staff", password_hash=hash_password(PW), role=m.STAFF))
        db.commit()
    yield


@pytest.fixture
def clock():
    return Clock


class Api:
    def __init__(self, client, token=None):
        self.c, self.h = client, ({"Authorization": f"Bearer {token}"} if token else {})

    def get(self, url, **kw): return self.c.get("/api" + url, headers=self.h, **kw)
    def post(self, url, json=None, **kw): return self.c.post("/api" + url, headers=self.h, json=json, **kw)
    def put(self, url, json=None): return self.c.put("/api" + url, headers=self.h, json=json)
    def patch(self, url, json=None, **kw): return self.c.patch("/api" + url, headers=self.h, json=json, **kw)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def login(client, email, pw=PW):
    r = client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return Api(client, r.json()["access_token"])


@pytest.fixture
def admin(client): return login(client, "admin@t.example.com")
@pytest.fixture
def staff(client): return login(client, "staff@t.example.com")


@pytest.fixture
def catalog(admin):
    """tax 10%, one product with a +560 'Odoo' brand variant, a monthly plan with a 100 fee."""
    tax = admin.post("/taxes", {"name": "T10", "rate": "10"}).json()
    term = admin.post("/payment-terms", {"name": "Net 15", "days": 15}).json()
    prod = admin.post("/products", {"name": "CRM", "sales_price": "1000", "tax_id": tax["id"], "type": "software",
                                    "variants": [{"attribute": "Brand", "value": "Odoo", "extra_price": "560"},
                                                 {"attribute": "Brand", "value": "Plain", "extra_price": "0"}]}).json()
    plan = admin.post("/plans", {"name": "Monthly", "price": "100", "interval": "monthly", "min_quantity": 2,
                                 "pausable": True, "renewable": True, "closable": True}).json()
    cust = admin.post("/customers", {"name": "Acme", "email": "acme@x.example.com"}).json()
    return dict(tax=tax, term=term, prod=prod, plan=plan, cust=cust,
                odoo=prod["variants"][0]["id"], plain=prod["variants"][1]["id"])


def make_active_sub(api, cat, qty=2, start="2025-01-01", expiry="2026-01-01", variant="plain", plan=None):
    r = api.post("/subscriptions", {
        "customer_id": cat["cust"]["id"], "plan_id": (plan or cat["plan"])["id"], "payment_term_id": cat["term"]["id"],
        "start_date": start, "expiry_date": expiry,
        "lines": [{"product_id": cat["prod"]["id"], "variant_id": cat[variant], "quantity": qty}]})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    for a in ("send_quote", "confirm", "activate"):
        t = api.post(f"/subscriptions/{sid}/transition", {"action": a})
        assert t.status_code == 200, t.text
    return sid
