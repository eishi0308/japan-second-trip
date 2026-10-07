"""Checkout: the demo path end to end, and the Stripe path against a fake client.

No test here talks to Stripe. The webhook test signs its own payload with the
same scheme Stripe uses, so signature verification is exercised for real.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from types import SimpleNamespace

import pytest

from jst_api.core.errors import ValidationFailedError
from jst_api.services.billing_service import BillingService

ROUTE = "Tokyo 3 nights, Sendai 2 nights, Aomori 2 nights, Tokyo"


async def _route_check_id(client) -> str:
    response = await client.post(
        "/api/v1/route-check", json={"itinerary_text": ROUTE, "save_trip": False}
    )
    assert response.status_code == 201
    return response.json()["analysis_id"]


class FakeStripe:
    """The two calls the service makes, and nothing else."""

    def __init__(self, payment_status: str = "unpaid") -> None:
        self.payment_status = payment_status
        self.created: list[dict] = []
        sessions = SimpleNamespace(create_async=self._create, retrieve_async=self._retrieve)
        self.v1 = SimpleNamespace(checkout=SimpleNamespace(sessions=sessions))

    async def _create(self, params: dict) -> SimpleNamespace:
        self.created.append(params)
        session_id = f"cs_test_{uuid.uuid4().hex}"
        return SimpleNamespace(id=session_id, url=f"https://checkout.stripe.test/c/{session_id}")

    async def _retrieve(self, session_id: str) -> SimpleNamespace:
        return SimpleNamespace(id=session_id, payment_status=self.payment_status)


def _stripe_settings(settings, **overrides):
    return settings.model_copy(
        update={"stripe_secret_key": "sk_test_abc", "stripe_webhook_secret": "whsec_test"}
        | overrides
    )


class TestDemoCheckout:
    async def test_config_reports_demo_mode_and_configured_prices(self, client, settings):
        body = (await client.get("/api/v1/billing/config")).json()
        assert body["mode"] == "demo"
        assert body["prices_aud"]["route_check"] == settings.price_route_check_aud

    async def test_a_purchase_is_pending_until_confirmed(self, client, settings):
        analysis_id = await _route_check_id(client)
        started = await client.post(
            "/api/v1/billing/checkout", json={"plan_id": "route_check", "analysis_id": analysis_id}
        )
        assert started.status_code == 201
        body = started.json()
        purchase = body["purchase"]
        assert body["mode"] == "demo"
        assert purchase["status"] == "pending"
        assert purchase["is_demo"] is True
        assert purchase["amount_aud"] == settings.price_route_check_aud
        assert body["checkout_url"].endswith(f"/checkout/demo?purchase={purchase['id']}")

        confirmed = await client.post(f"/api/v1/billing/purchases/{purchase['id']}/demo-confirm")
        assert confirmed.json()["status"] == "paid"
        assert confirmed.json()["paid_at"] is not None

        listed = (
            await client.get("/api/v1/billing/purchases", params={"analysis_id": analysis_id})
        ).json()
        assert [p["status"] for p in listed] == ["paid"]

    async def test_a_cancelled_checkout_stays_unpaid(self, client):
        started = await client.post("/api/v1/billing/checkout", json={"plan_id": "verified_route"})
        purchase_id = started.json()["purchase"]["id"]
        cancelled = await client.post(f"/api/v1/billing/purchases/{purchase_id}/cancel")
        assert cancelled.json()["status"] == "cancelled"

    async def test_the_free_plan_cannot_be_bought(self, client):
        response = await client.post("/api/v1/billing/checkout", json={"plan_id": "free"})
        assert response.status_code == 422

    async def test_a_plan_is_refused_against_the_wrong_kind_of_analysis(self, client):
        analysis_id = await _route_check_id(client)
        response = await client.post(
            "/api/v1/billing/checkout",
            json={"plan_id": "verified_route", "analysis_id": analysis_id},
        )
        assert response.status_code == 422

    async def test_an_unknown_analysis_is_a_404(self, client):
        response = await client.post(
            "/api/v1/billing/checkout", json={"plan_id": "route_check", "analysis_id": "an_nope"}
        )
        assert response.status_code == 404


class TestStripeCheckout:
    async def test_mode_follows_the_key(self, settings):
        assert BillingService(settings).mode == "demo"
        assert BillingService(_stripe_settings(settings)).mode == "stripe_test"
        live = _stripe_settings(settings, stripe_secret_key="sk_live_abc")
        assert BillingService(live).mode == "stripe_live"

    async def test_a_live_key_is_refused_outside_production(self, session_factory, settings):
        live = _stripe_settings(settings, stripe_secret_key="sk_live_abc")
        async with session_factory() as session:
            with pytest.raises(ValidationFailedError):
                await BillingService(live).start_checkout(
                    session, plan_id="route_check", analysis_id=None, trip_id=None
                )

    async def test_checkout_charges_the_configured_price_in_cents(self, session_factory, settings):
        fake = FakeStripe()
        service = BillingService(_stripe_settings(settings), stripe_client=fake)
        async with session_factory() as session:
            purchase, url = await service.start_checkout(
                session, plan_id="route_check", analysis_id=None, trip_id=None
            )
            await session.commit()

        params = fake.created[0]
        item = params["line_items"][0]["price_data"]
        assert item["currency"] == "aud"
        assert item["unit_amount"] == settings.price_route_check_aud * 100
        assert params["metadata"]["purchase_id"] == purchase.id
        assert purchase.provider_session_id.startswith("cs_test_")
        assert purchase.status == "pending"
        assert url.startswith("https://checkout.stripe.test/")

    async def test_sync_settles_only_once_stripe_reports_payment(self, session_factory, settings):
        fake = FakeStripe(payment_status="unpaid")
        service = BillingService(_stripe_settings(settings), stripe_client=fake)
        async with session_factory() as session:
            purchase, _ = await service.start_checkout(
                session, plan_id="verified_route", analysis_id=None, trip_id=None
            )
            assert (await service.sync(session, purchase.id)).status == "pending"
            fake.payment_status = "paid"
            assert (await service.sync(session, purchase.id)).status == "paid"
            await session.commit()

    async def test_a_stripe_purchase_cannot_be_demo_confirmed(
        self, client, session_factory, settings
    ):
        service = BillingService(_stripe_settings(settings), stripe_client=FakeStripe())
        async with session_factory() as session:
            purchase, _ = await service.start_checkout(
                session, plan_id="route_check", analysis_id=None, trip_id=None
            )
            await session.commit()
        response = await client.post(f"/api/v1/billing/purchases/{purchase.id}/demo-confirm")
        assert response.status_code == 409

    async def test_a_signed_webhook_marks_the_purchase_paid(self, session_factory, settings):
        configured = _stripe_settings(settings)
        service = BillingService(configured, stripe_client=FakeStripe())
        async with session_factory() as session:
            purchase, _ = await service.start_checkout(
                session, plan_id="route_check", analysis_id=None, trip_id=None
            )
            payload = json.dumps(
                {
                    "id": "evt_1",
                    "object": "event",
                    "type": "checkout.session.completed",
                    "data": {
                        "object": {
                            "id": purchase.provider_session_id,
                            "object": "checkout.session",
                            "payment_status": "paid",
                        }
                    },
                }
            ).encode()
            stamp = int(time.time())
            digest = hmac.new(
                b"whsec_test", f"{stamp}.".encode() + payload, hashlib.sha256
            ).hexdigest()

            with pytest.raises(ValidationFailedError):
                await service.handle_webhook(session, payload, f"t={stamp},v1={'0' * 64}")
            assert purchase.status == "pending"

            outcome = await service.handle_webhook(session, payload, f"t={stamp},v1={digest}")
            assert outcome == "paid"
            assert purchase.status == "paid"
            await session.commit()
