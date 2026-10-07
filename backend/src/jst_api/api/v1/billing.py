"""Checkout and purchase records. Traveller-initiated only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from jst_api.api.deps import RateLimitDep, SessionDep, SettingsDep
from jst_api.api.schemas import BillingConfigOut, CheckoutIn, CheckoutOut, PurchaseOut
from jst_api.db.models import Purchase
from jst_api.services.billing_service import BillingService, plan_name

router = APIRouter(prefix="/billing", tags=["billing"])


def get_billing(settings: SettingsDep) -> BillingService:
    return BillingService(settings)


BillingDep = Annotated[BillingService, Depends(get_billing)]


def _out(purchase: Purchase) -> PurchaseOut:
    return PurchaseOut(
        id=purchase.id,
        plan_id=purchase.plan_id,
        plan_name=plan_name(purchase.plan_id),
        amount_aud=purchase.amount_aud,
        status=purchase.status,
        provider=purchase.provider,
        is_demo=purchase.is_demo,
        analysis_id=purchase.analysis_id,
        trip_id=purchase.trip_id,
        paid_at=purchase.paid_at,
    )


@router.get("/config", response_model=BillingConfigOut)
async def billing_config(billing: BillingDep) -> BillingConfigOut:
    return BillingConfigOut(
        mode=billing.mode,
        currency="aud",
        prices_aud={
            "verified_route": billing.price_aud("verified_route"),
            "route_check": billing.price_aud("route_check"),
        },
    )


@router.post("/checkout", response_model=CheckoutOut, status_code=201)
async def start_checkout(
    payload: CheckoutIn, session: SessionDep, billing: BillingDep, _rate: RateLimitDep
) -> CheckoutOut:
    purchase, url = await billing.start_checkout(
        session,
        plan_id=payload.plan_id,
        analysis_id=payload.analysis_id,
        trip_id=payload.trip_id,
    )
    return CheckoutOut(purchase=_out(purchase), checkout_url=url, mode=billing.mode)


@router.get("/purchases", response_model=list[PurchaseOut])
async def list_purchases(
    analysis_id: str, session: SessionDep, billing: BillingDep
) -> list[PurchaseOut]:
    return [_out(p) for p in await billing.list_for_analysis(session, analysis_id)]


@router.get("/purchases/{purchase_id}", response_model=PurchaseOut)
async def get_purchase(purchase_id: str, session: SessionDep, billing: BillingDep) -> PurchaseOut:
    return _out(await billing.get(session, purchase_id))


@router.post("/purchases/{purchase_id}/demo-confirm", response_model=PurchaseOut)
async def confirm_demo_purchase(
    purchase_id: str, session: SessionDep, billing: BillingDep, _rate: RateLimitDep
) -> PurchaseOut:
    return _out(await billing.confirm_demo(session, purchase_id))


@router.post("/purchases/{purchase_id}/cancel", response_model=PurchaseOut)
async def cancel_purchase(
    purchase_id: str, session: SessionDep, billing: BillingDep, _rate: RateLimitDep
) -> PurchaseOut:
    return _out(await billing.cancel(session, purchase_id))


@router.post("/purchases/{purchase_id}/sync", response_model=PurchaseOut)
async def sync_purchase(
    purchase_id: str, session: SessionDep, billing: BillingDep, _rate: RateLimitDep
) -> PurchaseOut:
    return _out(await billing.sync(session, purchase_id))


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    session: SessionDep,
    billing: BillingDep,
    stripe_signature: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    outcome = await billing.handle_webhook(session, await request.body(), stripe_signature)
    return {"status": outcome}
