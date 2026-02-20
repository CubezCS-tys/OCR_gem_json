"""
Stripe integration for ScanToText.

All user/subscription state is persisted in SQLite via db.py.
In-memory dict is gone — restarts no longer lose user data.
"""

from __future__ import annotations

import logging
import os
import time

import stripe
from sqlalchemy.orm import Session

from db import User, get_or_create_user

logger = logging.getLogger(__name__)

# ── Stripe Config ─────────────────────────────────────────────────────────────
stripe.api_key          = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY  = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET   = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID         = os.getenv("STRIPE_PRICE_ID", "")
BASE_URL                = os.getenv("BASE_URL", "http://localhost:8000")

MONTHLY_PAGE_LIMIT = int(os.getenv("MONTHLY_PAGE_LIMIT", "2000"))
PLAN_PRICE_DISPLAY = os.getenv("PLAN_PRICE_DISPLAY", "£20")
TRIAL_DAYS         = int(os.getenv("TRIAL_DAYS", "7"))
TRIAL_PAGE_LIMIT   = int(os.getenv("TRIAL_PAGE_LIMIT", "1000"))

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("true", "1", "yes")


# ── Trial ─────────────────────────────────────────────────────────────────────

def start_free_trial(db: Session, email: str) -> User:
    """
    Activate a free trial for a new or lapsed user.
    No-ops if the user already has an active subscription or live trial.
    """
    user = get_or_create_user(db, email)
    if user.is_subscribed:
        return user
    if user.trial_active:
        return user
    user.is_trial        = True
    user.trial_expires   = time.time() + TRIAL_DAYS * 86_400
    user.page_limit      = TRIAL_PAGE_LIMIT
    user.pages_used      = 0
    user.period_start    = time.time()
    db.commit()
    db.refresh(user)
    logger.info("Free trial started for %s (%d days, %d pages)", email, TRIAL_DAYS, TRIAL_PAGE_LIMIT)
    return user


# ── Demo / dev auto-approve ───────────────────────────────────────────────────

def demo_activate(db: Session, email: str) -> User:
    """Auto-activate with full Pro limits (demo / no-Stripe-key mode)."""
    user = get_or_create_user(db, email)
    user.is_subscribed = True
    user.page_limit    = MONTHLY_PAGE_LIMIT
    user.pages_used    = 0
    user.period_start  = time.time()
    db.commit()
    db.refresh(user)
    logger.info("DEMO: Auto-subscribed %s", email)
    return user


# ── Stripe Checkout ───────────────────────────────────────────────────────────

def create_subscription_checkout(email: str) -> str:
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        customer_email=email,
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
        success_url=f"{BASE_URL}/subscribe/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{BASE_URL}/subscribe/cancel",
        metadata={"email": email},
    )
    return session.url


def create_customer_portal(customer_id: str) -> str:
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{BASE_URL}/",
    )
    return session.url


# ── Webhooks ──────────────────────────────────────────────────────────────────

def verify_webhook(payload: bytes, sig_header: str) -> dict | None:
    try:
        return stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as exc:
        logger.warning("Webhook verification failed: %s", exc)
        return None


def handle_webhook_event(event: dict, db: Session) -> None:
    """Process Stripe webhook events. Needs a DB session."""
    etype = event["type"]
    data  = event["data"]["object"]

    if etype == "checkout.session.completed":
        email    = data.get("customer_email") or data.get("metadata", {}).get("email", "")
        cust_id  = data.get("customer", "")
        sub_id   = data.get("subscription", "")
        if email:
            user = get_or_create_user(db, email)
            user.stripe_customer_id      = cust_id
            user.stripe_subscription_id  = sub_id
            user.is_subscribed           = True
            user.is_trial                = False
            user.page_limit              = MONTHLY_PAGE_LIMIT
            user.pages_used              = 0
            user.period_start            = time.time()
            db.commit()
            logger.info("Subscription activated for %s", email)

    elif etype in ("customer.subscription.updated", "customer.subscription.created"):
        cust_id = data.get("customer", "")
        status_ = data.get("status", "")
        user = db.query(User).filter(User.stripe_customer_id == cust_id).first()
        if user:
            user.is_subscribed = (status_ == "active")
            period = data.get("current_period_start", 0)
            if period and period != user.current_period_start:
                user.current_period_start = period
                user.current_period_end   = data.get("current_period_end", 0)
                user.pages_used           = 0   # new billing period
                logger.info("Page count reset for %s (new period)", user.email)
            db.commit()

    elif etype == "customer.subscription.deleted":
        cust_id = data.get("customer", "")
        user = db.query(User).filter(User.stripe_customer_id == cust_id).first()
        if user:
            user.is_subscribed = False
            db.commit()
            logger.info("Subscription cancelled for %s", user.email)

    elif etype == "invoice.paid":
        cust_id = data.get("customer", "")
        user = db.query(User).filter(User.stripe_customer_id == cust_id).first()
        if user:
            user.pages_used = 0
            db.commit()
            logger.info("Invoice paid, pages reset for %s", user.email)


def verify_checkout_session(session_id: str, db: Session) -> dict | None:
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.status == "complete":
            email = session.customer_email or session.metadata.get("email", "")
            user  = get_or_create_user(db, email)
            user.stripe_customer_id      = session.customer or ""
            user.stripe_subscription_id  = session.subscription or ""
            user.is_subscribed           = True
            user.page_limit              = MONTHLY_PAGE_LIMIT
            user.pages_used              = 0
            db.commit()
            return {"email": email, "customer_id": session.customer}
    except Exception as exc:
        logger.error("Session verification failed: %s", exc)
    return None
