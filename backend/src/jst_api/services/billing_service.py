"""Checkout for the paid plans.

Two paths behind one interface, like every other external dependency here:

* **Stripe Checkout** when ``STRIPE_SECRET_KEY`` is set. The card form is
  Stripe's hosted page — no card detail ever reaches this service.
* **Demo checkout** otherwise: the same purchase lifecycle with no card and no
  charge, labelled as demo wherever it surfaces.

Payment is only ever started by a traveller pressing a button. No agent, graph
node or MCP tool can reach this module; that boundary is deliberate.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.core.config import Settings
from jst_api.core.errors import (
    ConflictError,
    NotFoundError,
    ProviderError,
    ValidationFailedError,
)
from jst_api.core.logging import get_logger
from jst_api.db.models import Analysis, Purchase

log = get_logger(__name__)

BillingMode = Literal["demo", "stripe_test", "stripe_live"]

#: plan id -> (display name, the analysis kind it is sold against)
PAID_PLANS: dict[str, tuple[str, str]] = {
    "verified_route": ("Verified Regional Route", "where_next"),
    "route_check": ("RouteCheck", "route_check"),
}


def plan_name(plan_id: str) -> str:
    return PAID_PLANS[plan_id][0] if plan_id in PAID_PLANS else plan_id


class BillingService:
    def __init__(self, settings: Settings, *, stripe_client: Any | None = None) -> None:
        self._settings = settings
        self._stripe = stripe_client

    # ---- configuration -----------------------------------------------------
    @property
    def mode(self) -> BillingMode:
        key = self._settings.stripe_secret_key
        if not key:
            return "demo"
        return "stripe_live" if key.startswith(("sk_live_", "rk_live_")) else "stripe_test"

    def price_aud(self, plan_id: str) -> int:
        prices = {
            "verified_route": self._settings.price_verified_route_aud,
            "route_check": self._settings.price_route_check_aud,
        }
        if plan_id not in prices:
            raise ValidationFailedError(
                f"'{plan_id}' is not a purchasable plan", details={"plan_id": plan_id}
            )
        return prices[plan_id]

    def _client(self) -> Any:
        if self.mode == "stripe_live" and self._settings.environment != "production":
            raise ValidationFailedError(
                "A live Stripe key is refused outside production. Use a test key (sk_test_…)."
            )
        if self._stripe is None:
            key = self._settings.stripe_secret_key
            if not key:
                raise ValidationFailedError("Stripe is not configured; billing is in demo mode.")
            import stripe

            self._stripe = stripe.StripeClient(key, max_network_retries=2)
        return self._stripe

    # ---- lifecycle ---------------------------------------------------------
    async def start_checkout(
        self,
        session: AsyncSession,
        *,
        plan_id: str,
        analysis_id: str | None,
        trip_id: str | None,
    ) -> tuple[Purchase, str]:
        amount = self.price_aud(plan_id)
        if amount <= 0:
            raise ValidationFailedError(f"'{plan_id}' is free; there is nothing to pay for.")

        if analysis_id is not None:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                raise NotFoundError(
                    f"Analysis {analysis_id} not found", details={"analysis_id": analysis_id}
                )
            if analysis.kind != PAID_PLANS[plan_id][1]:
                raise ValidationFailedError(
                    f"{plan_name(plan_id)} is not sold against a {analysis.kind} analysis."
                )
            trip_id = trip_id or analysis.trip_id

        web = self._settings.public_web_url.rstrip("/")
        if self.mode == "demo":
            purchase = Purchase(
                plan_id=plan_id,
                amount_aud=amount,
                provider="demo",
                is_demo=True,
                analysis_id=analysis_id,
                trip_id=trip_id,
            )
            session.add(purchase)
            await session.flush()
            log.info("billing.checkout_started", purchase_id=purchase.id, provider="demo")
            return purchase, f"{web}/checkout/demo?purchase={purchase.id}"

        client = self._client()
        purchase = Purchase(
            plan_id=plan_id,
            amount_aud=amount,
            provider="stripe",
            is_demo=False,
            analysis_id=analysis_id,
            trip_id=trip_id,
        )
        session.add(purchase)
        await session.flush()
        try:
            checkout = await asyncio.wait_for(
                client.v1.checkout.sessions.create_async(
                    params={
                        "mode": "payment",
                        "line_items": [
                            {
                                "quantity": 1,
                                "price_data": {
                                    "currency": "aud",
                                    "unit_amount": amount * 100,
                                    "product_data": {"name": plan_name(plan_id)},
                                },
                            }
                        ],
                        "client_reference_id": purchase.id,
                        "metadata": {"purchase_id": purchase.id, "plan_id": plan_id},
                        "success_url": f"{web}/checkout/return?purchase={purchase.id}",
                        "cancel_url": f"{web}/checkout/return?purchase={purchase.id}&cancelled=1",
                    }
                ),
                timeout=self._settings.external_timeout_seconds,
            )
        except Exception as exc:
            log.warning("billing.stripe_checkout_failed", error=type(exc).__name__)
            raise ProviderError("Stripe could not start the checkout. Try again shortly.") from exc
        purchase.provider_session_id = checkout.id
        await session.flush()
        log.info("billing.checkout_started", purchase_id=purchase.id, provider="stripe")
        return purchase, str(checkout.url)

    async def get(self, session: AsyncSession, purchase_id: str) -> Purchase:
        purchase = await session.get(Purchase, purchase_id)
        if purchase is None:
            raise NotFoundError(
                f"Purchase {purchase_id} not found", details={"purchase_id": purchase_id}
            )
        return purchase

    async def list_for_analysis(self, session: AsyncSession, analysis_id: str) -> list[Purchase]:
        rows = await session.scalars(
            select(Purchase)
            .where(Purchase.analysis_id == analysis_id)
            .order_by(Purchase.created_at.desc())
        )
        return list(rows)

    async def confirm_demo(self, session: AsyncSession, purchase_id: str) -> Purchase:
        purchase = await self.get(session, purchase_id)
        if purchase.provider != "demo":
            raise ConflictError("Only a demo checkout can be confirmed without a payment.")
        return await self._mark_paid(session, purchase)

    async def cancel(self, session: AsyncSession, purchase_id: str) -> Purchase:
        purchase = await self.get(session, purchase_id)
        if purchase.status == "pending":
            purchase.status = "cancelled"
            await session.flush()
        return purchase

    async def sync(self, session: AsyncSession, purchase_id: str) -> Purchase:
        """Ask Stripe what happened. Lets the return page settle a payment even
        where no webhook can reach this process (local development)."""
        purchase = await self.get(session, purchase_id)
        if purchase.provider != "stripe" or purchase.status == "paid":
            return purchase
        if not purchase.provider_session_id:
            return purchase
        try:
            checkout = await asyncio.wait_for(
                self._client().v1.checkout.sessions.retrieve_async(purchase.provider_session_id),
                timeout=self._settings.external_timeout_seconds,
            )
        except ValidationFailedError:
            raise
        except Exception as exc:
            log.warning("billing.stripe_sync_failed", error=type(exc).__name__)
            raise ProviderError("Stripe could not confirm the payment. Try again shortly.") from exc
        if getattr(checkout, "payment_status", None) == "paid":
            return await self._mark_paid(session, purchase)
        return purchase

    async def handle_webhook(
        self, session: AsyncSession, payload: bytes, signature: str | None
    ) -> str:
        secret = self._settings.stripe_webhook_secret
        if not secret:
            raise ValidationFailedError("STRIPE_WEBHOOK_SECRET is not configured.")
        import stripe

        try:
            event = stripe.Webhook.construct_event(payload, signature, secret)
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise ValidationFailedError("Webhook signature could not be verified.") from exc

        if event.type != "checkout.session.completed":
            return "ignored"
        checkout: Any = event.data.object
        purchase = await session.scalar(
            select(Purchase).where(Purchase.provider_session_id == checkout.id)
        )
        if purchase is None or getattr(checkout, "payment_status", None) != "paid":
            return "ignored"
        await self._mark_paid(session, purchase)
        return "paid"

    async def _mark_paid(self, session: AsyncSession, purchase: Purchase) -> Purchase:
        if purchase.status != "paid":
            purchase.status = "paid"
            purchase.paid_at = datetime.now(UTC)
            await session.flush()
            log.info("billing.paid", purchase_id=purchase.id, provider=purchase.provider)
        return purchase
