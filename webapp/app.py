"""
ScanToText — B2C OCR Web App.

Auth flow
---------
1. GET  /auth/google                 → redirect to Google consent screen
2. GET  /auth/google/callback        → exchange code, issue JWT, redirect home
3. All pro API calls include  Authorization: Bearer <jwt>

Free tier: no auth required.
Pro tier:  JWT required.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent / ".env", override=True)

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# ── Internal modules ──────────────────────────────────────────────────────────
import db as _db
from db import (
    User,
    consume_pages,
    create_job,
    delete_job,
    get_db,
    get_job,
    get_jobs_expired,
    get_or_create_user,
    get_user_jobs,
    init_db,
    update_job,
)
from auth import (
    build_google_auth_url,
    create_access_token,
    exchange_google_code,
    get_current_user,
    get_optional_user,
    require_active_user,
)
from ocr_service import (
    SUPPORTED_IMAGE_EXTS,
    SUPPORTED_PDF_EXTS,
    count_pages,
    generate_searchable_pdf_only,
    package_results,
    process_document,
)

import stripe as _stripe
from stripe_service import (
    BASE_URL,
    DEMO_MODE,
    MONTHLY_PAGE_LIMIT,
    PLAN_PRICE_DISPLAY,
    STRIPE_PUBLISHABLE_KEY,
    TRIAL_DAYS,
    TRIAL_PAGE_LIMIT,
    create_customer_portal,
    create_subscription_checkout,
    demo_activate,
    handle_webhook_event,
    start_free_trial,
    verify_checkout_session,
    verify_webhook,
)

# ── Setup ─────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("scantotext")

MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE    = MAX_FILE_SIZE_MB * 1024 * 1024
# How old (seconds) a job directory must be before the cleanup task removes it.
UPLOAD_MAX_AGE_SECS = int(os.getenv("UPLOAD_MAX_AGE_HOURS", "24")) * 3600
# Max pages allowed for a single free (guest) conversion
FREE_MAX_PAGES = int(os.getenv("FREE_MAX_PAGES", "5"))

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# ── Rate limiter ──────────────────────────────────────────────────────────────
def _real_ip(request: Request) -> str:
    """Read the real client IP from nginx-forwarded headers.
    Falls back to request.client.host when not behind a proxy.
    """
    return (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
limiter = Limiter(key_func=_real_ip, default_limits=[], storage_uri=_REDIS_URL, key_style="endpoint")

app = FastAPI(title="ScanToText", version="3.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Restrict CORS to the same origin in production; fall back to * in dev.
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", BASE_URL).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── DB init on startup ────────────────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    # Guard: warn loudly if JWT_SECRET is the insecure default
    raw_jwt_secret = os.getenv("JWT_SECRET", "")
    if not raw_jwt_secret:
        logger.warning(
            "JWT_SECRET is not set — tokens are signed with an ephemeral key. "
            "Set JWT_SECRET in .env to a strong random value for production."
        )
    # Guard: warn if Stripe keys look like placeholders
    stripe_key = os.getenv("STRIPE_SECRET_KEY", "")
    if stripe_key.startswith("sk_test_") and os.getenv("DEMO_MODE", "0") not in ("1", "true", "yes"):
        logger.warning(
            "STRIPE_SECRET_KEY is a test key but DEMO_MODE is off. "
            "Switch to sk_live_... before going live."
        )
    if not os.getenv("STRIPE_WEBHOOK_SECRET", "").startswith("whsec_"):
        logger.warning("STRIPE_WEBHOOK_SECRET appears unset or invalid — webhooks will be rejected.")

    init_db()
    if _db.DB_PATH:
        logger.info("SQLite DB ready at %s", _db.DB_PATH)
    else:
        logger.info("PostgreSQL DB ready (DATABASE_URL)")

    # Pre-warm the OCR pipeline imports so the first user request is fast.
    # Each gunicorn worker pays this cost once at boot instead of on first click.
    try:
        import sys as _sys
        _root = str(Path(__file__).resolve().parent.parent)
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from fixed_layout_pipeline.config import AzureConfig  # noqa: F401
        from fixed_layout_pipeline.searchable_pdf import (  # noqa: F401
            generate_searchable_pdf,
            generate_searchable_pdf_from_bytes,
        )
        logger.info("OCR pipeline modules pre-loaded (worker warm-up OK)")
    except Exception as _e:
        logger.warning("OCR pipeline warm-up failed (will import on first request): %s", _e)

    # Start the background upload-cleanup task
    asyncio.get_event_loop().create_task(_cleanup_uploads_loop())


async def _cleanup_uploads_loop() -> None:
    """Periodically delete job directories older than UPLOAD_MAX_AGE_SECS."""
    while True:
        await asyncio.sleep(3600)   # run every hour
        _run_upload_cleanup()


def _run_upload_cleanup() -> None:
    """Delete job dirs and DB records whose per-job retention window has expired.

    Free / anonymous jobs: 1 day (retention_days=1).
    Pro subscriber jobs:   30 days (set by process_pro).
    """
    db = _db.SessionLocal()
    removed = 0
    try:
        expired_jobs = get_jobs_expired(db)
        for job in expired_jobs:
            # Remove the filesystem work directory
            work_dir = Path(job.work_dir)
            if work_dir.exists():
                try:
                    shutil.rmtree(work_dir)
                    removed += 1
                except Exception as exc:
                    logger.warning("Cleanup error for %s: %s", work_dir, exc)
            # Remove result file if it lives outside the work dir
            if job.result_path:
                result = Path(job.result_path)
                if result.exists() and not str(result).startswith(str(work_dir)):
                    try:
                        result.unlink()
                    except Exception:
                        pass
            # Delete the DB record
            db.delete(job)
        if expired_jobs:
            db.commit()
            logger.info(
                "Upload cleanup: removed %d expired job%s (%d dir%s deleted)",
                len(expired_jobs), "" if len(expired_jobs) == 1 else "s",
                removed, "" if removed == 1 else "s",
            )
    except Exception as exc:
        logger.warning("DB job cleanup error: %s", exc)
    finally:
        db.close()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return {
        "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY,
        "plan_price": PLAN_PRICE_DISPLAY,
        "monthly_page_limit": MONTHLY_PAGE_LIMIT,
        "free_max_pages": FREE_MAX_PAGES,
        "max_file_size_mb": MAX_FILE_SIZE_MB,
        "supported_formats": sorted(SUPPORTED_IMAGE_EXTS | SUPPORTED_PDF_EXTS),
        "demo_mode": DEMO_MODE,
        "pro_formats": [
            {"id": "searchable_pdf",  "name": "Searchable PDF",      "desc": "Text-selectable PDF"},
            {"id": "pixel_html",      "name": "Pixel-Perfect HTML",  "desc": "Exact layout with positioned text"},
            {"id": "semantic_html",   "name": "Semantic HTML",       "desc": "Reflowed HTML (Gemini)"},
            {"id": "markdown",        "name": "Markdown + Images",   "desc": "Clean markdown (Mistral)"},
        ],
    }


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/auth/google")
async def google_login():
    """Redirect user to Google OAuth consent screen."""
    from auth import GOOGLE_CLIENT_ID
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Google OAuth not configured — set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env")
    state = secrets.token_urlsafe(16)
    auth_url = build_google_auth_url(state)
    resp = RedirectResponse(auth_url, status_code=302)
    resp.set_cookie("oauth_state", state, max_age=600, httponly=True, samesite="lax")
    return resp


@app.get("/auth/google/callback")
async def google_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
    db: Session = Depends(get_db),
):
    """Handle Google OAuth callback: verify state, get email, issue JWT."""
    if error:
        logger.warning("Google OAuth error: %s", error)
        return RedirectResponse(f"/?auth_error={error}")

    stored_state = request.cookies.get("oauth_state")
    if not stored_state or stored_state != state:
        logger.warning("OAuth state mismatch")
        return RedirectResponse("/?auth_error=state_mismatch")

    try:
        email = await exchange_google_code(code)
    except HTTPException:
        return RedirectResponse("/?auth_error=google_failed")

    get_or_create_user(db, email)
    jwt_token = create_access_token(email)

    resp = RedirectResponse(f"/?token={jwt_token}&email={email}")
    resp.delete_cookie("oauth_state")
    return resp


@app.post("/api/auth/demo-login")
async def demo_login(email: str, db: Session = Depends(get_db)):
    """
    Dev/demo shortcut — only works when DEMO_MODE=1.
    Returns a JWT immediately without going through Google.
    """
    if not DEMO_MODE:
        raise HTTPException(403, "Demo login only available in DEMO_MODE")
    email = email.lower().strip()
    if not email or "@" not in email:
        raise HTTPException(400, "Valid email required")
    demo_activate(db, email)
    jwt = create_access_token(email)
    return {"token": jwt, "email": email, "demo_mode": True}


# ── Trial ─────────────────────────────────────────────────────────────────────

@app.post("/api/trial")
async def begin_trial(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Activate free trial for the authenticated user."""
    user = start_free_trial(db, current_user.email)
    return {
        "email": user.email,
        "is_trial": user.is_trial,
        "trial_days": TRIAL_DAYS,
        "page_limit": user.page_limit,
        "trial_expires": user.trial_expires,
    }


# ── Account ───────────────────────────────────────────────────────────────────

@app.get("/api/account")
async def get_account(current_user: User = Depends(get_current_user)):
    """Return authenticated user's subscription + usage status."""
    trial_days_left = None
    if current_user.is_trial and current_user.trial_expires:
        trial_days_left = max(0, int((current_user.trial_expires - time.time()) / 86_400))
    return {
        "email":           current_user.email,
        "is_subscribed":   current_user.is_subscribed,
        "is_trial":        current_user.is_trial,
        "trial_active":    current_user.trial_active,
        "trial_days_left": trial_days_left,
        "is_active":       current_user.is_active,
        "pages_used":      current_user.pages_used,
        "page_limit":      current_user.page_limit,
        "pages_remaining": current_user.pages_remaining,
    }


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/api/dashboard")
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the authenticated user's job history (newest first, up to 100)."""
    import json as _json

    jobs = get_user_jobs(db, current_user.id, limit=100)

    job_list = []
    for job in jobs:
        expires_at  = job.created_at + (job.retention_days or 1) * 86400
        is_expired  = time.time() > expires_at
        file_exists = bool(job.result_path and Path(job.result_path).exists())

        download_url = None
        if job.status == "done" and file_exists and not is_expired:
            download_url = f"/api/download/{job.job_id}"

        formats_produced = []
        if job.results:
            try:
                formats_produced = [k for k, v in _json.loads(job.results).items() if v]
            except Exception:
                pass

        job_list.append({
            "job_id":           job.job_id,
            "filename":         job.filename,
            "page_count":       job.page_count,
            "file_size":        job.file_size,
            "status":           job.status,
            "type":             job.type,
            "formats_produced": formats_produced,
            "created_at":       job.created_at,
            "expires_at":       expires_at,
            "is_expired":       is_expired,
            "download_url":     download_url,
        })

    trial_days_left = None
    if current_user.is_trial and current_user.trial_expires:
        trial_days_left = max(0, int((current_user.trial_expires - time.time()) / 86_400))

    return {
        "email":           current_user.email,
        "is_subscribed":   current_user.is_subscribed,
        "is_active":       current_user.is_active,
        "is_trial":        current_user.is_trial,
        "trial_days_left": trial_days_left,
        "pages_used":      current_user.pages_used,
        "page_limit":      current_user.page_limit,
        "pages_remaining": current_user.pages_remaining,
        "jobs":            job_list,
    }


# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/api/upload")
@limiter.limit("30/minute")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    """Upload accepts any user — free tier needs no auth.
    If a valid JWT is provided the job is linked to that user's account.
    """
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in (SUPPORTED_IMAGE_EXTS | SUPPORTED_PDF_EXTS):
        raise HTTPException(400, f"Unsupported format: {ext}")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large. Max: {MAX_FILE_SIZE_MB} MB")
    if len(contents) == 0:
        raise HTTPException(400, "File is empty")

    page_count = count_pages(contents, file.filename)

    job_id   = str(uuid.uuid4())
    work_dir = UPLOAD_DIR / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / file.filename).write_bytes(contents)

    user_id = current_user.id if current_user else None
    create_job(
        db,
        job_id=job_id,
        filename=file.filename,
        file_size=len(contents),
        page_count=page_count,
        work_dir=str(work_dir),
        user_id=user_id,
    )

    logger.info(
        "Uploaded %s (%d KB, %d pages) → %s [user=%s]",
        file.filename, len(contents) // 1024, page_count, job_id,
        current_user.email if current_user else "anon",
    )

    return {"job_id": job_id, "filename": file.filename, "file_size": len(contents), "page_count": page_count}


# ── Free Tier ─────────────────────────────────────────────────────────────────

@app.post("/api/process/free/{job_id}")
@limiter.limit("5/hour")
async def process_free(request: Request, job_id: str, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "uploaded":
        raise HTTPException(400, f"Job already in state: {job.status}")
    if job.page_count > FREE_MAX_PAGES:
        raise HTTPException(
            400,
            f"Free conversions are limited to {FREE_MAX_PAGES} pages. "
            f"This document has {job.page_count} pages — sign in for Pro access."
        )

    update_job(db, job_id, status="processing", type="free")

    try:
        work_dir   = Path(job.work_dir)
        file_bytes = (work_dir / job.filename).read_bytes()
        result_path = await asyncio.to_thread(
            generate_searchable_pdf_only, file_bytes, job.filename, work_dir
        )
        update_job(db, job_id, status="done", result_path=str(result_path))
    except Exception as exc:
        update_job(db, job_id, status="error", error_msg=str(exc))
        raise HTTPException(500, f"Processing failed: {exc}")

    return {"job_id": job_id, "status": "done", "download_url": f"/api/download/{job_id}"}


# ── Pro Tier ──────────────────────────────────────────────────────────────────

@app.post("/api/process/pro/{job_id}")
async def process_pro(
    job_id:       str,
    formats:      str = "",
    current_user: User = Depends(require_active_user),
    db:           Session = Depends(get_db),
):
    """
    Pro processing — requires valid JWT (Authorization: Bearer <token>).
    'formats' is an optional comma-separated list; defaults to all.
    """
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "uploaded":
        raise HTTPException(400, f"Job already in state: {job.status}")

    page_count = job.page_count
    if not current_user.can_process(page_count):
        raise HTTPException(
            429,
            f"Page limit reached. Used: {current_user.pages_used}/{current_user.page_limit}. "
            f"This document needs {page_count} pages."
        )

    import json as _json

    all_formats = ["searchable_pdf", "pixel_html", "semantic_html", "markdown"]
    requested   = [f.strip() for f in formats.split(",") if f.strip() in all_formats] if formats else all_formats

    update_job(db, job_id, status="processing", type="pro")

    try:
        work_dir   = Path(job.work_dir)
        file_bytes = (work_dir / job.filename).read_bytes()

        results = await asyncio.to_thread(
            process_document, file_bytes, job.filename, work_dir, requested
        )

        produced = [k for k, v in results.items() if v is not None]
        if not produced:
            raise HTTPException(500, "All pipelines failed — check your API credentials in .env.")

        stem     = Path(job.filename).stem
        zip_path = await asyncio.to_thread(package_results, results, stem, work_dir)

        results_dict = {k: str(v) if v else None for k, v in results.items()}
        # Pro users get 30-day result retention; link job to their account
        update_job(
            db, job_id,
            status="done",
            result_path=str(zip_path),
            results=_json.dumps(results_dict),
            retention_days=30,
            user_id=current_user.id,
        )

        # Atomically persist page consumption
        consume_pages(db, current_user, page_count)
        db.refresh(current_user)

        logger.info("Pro done: %s — %d pages, formats: %s", job_id, page_count, produced)

    except HTTPException:
        update_job(db, job_id, status="error")
        raise
    except Exception as exc:
        update_job(db, job_id, status="error", error_msg=str(exc))
        raise HTTPException(500, f"Processing failed: {exc}")

    return {
        "job_id":           job_id,
        "status":           "done",
        "download_url":     f"/api/download/{job_id}",
        "pages_used":       page_count,
        "pages_remaining":  current_user.pages_remaining,
        "formats_produced": produced,
        "formats":          produced,
        "filename":         job.filename,
    }


# ── Stripe / Subscription ─────────────────────────────────────────────────────

@app.post("/api/subscribe")
async def subscribe(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kick off Stripe Checkout (or auto-approve in demo mode)."""
    no_stripe_key = not _stripe.api_key
    if DEMO_MODE or no_stripe_key:
        demo_activate(db, current_user.email)
        return {"demo_mode": True, "email": current_user.email}
    try:
        url = create_subscription_checkout(current_user.email)
        return {"url": url}
    except Exception as exc:
        raise HTTPException(500, f"Subscription setup failed: {exc}")


@app.get("/subscribe/success")
async def subscribe_success(session_id: str, db: Session = Depends(get_db)):
    result = verify_checkout_session(session_id, db)
    if result:
        jwt = create_access_token(result["email"])
        return RedirectResponse(f"/?token={jwt}&email={result['email']}")
    return RedirectResponse("/?subscribe_error=1")


@app.get("/subscribe/cancel")
async def subscribe_cancel():
    return RedirectResponse("/?subscribe_cancelled=1")


@app.post("/api/manage-subscription")
async def manage_subscription(
    current_user: User = Depends(get_current_user),
):
    if not current_user.stripe_customer_id:
        raise HTTPException(400, "No Stripe subscription on file")
    try:
        url = create_customer_portal(current_user.stripe_customer_id)
        return {"portal_url": url}
    except Exception as exc:
        raise HTTPException(500, f"Portal creation failed: {exc}")


@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig     = request.headers.get("stripe-signature", "")
    event   = verify_webhook(payload, sig)
    if not event:
        raise HTTPException(400, "Invalid webhook")
    handle_webhook_event(event, db)
    return JSONResponse({"received": True})


# ── Jobs / Download ───────────────────────────────────────────────────────────

@app.get("/api/status/{job_id}")
async def get_status(job_id: str, db: Session = Depends(get_db)):
    import json as _json
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    result: dict = {
        "job_id":     job_id,
        "filename":   job.filename,
        "page_count": job.page_count,
        "status":     job.status,
        "type":       job.type,
    }
    if job.status == "done":
        result["download_url"]     = f"/api/download/{job_id}"
        result["formats_produced"] = [k for k, v in _json.loads(job.results or "{}").items() if v]
    if job.error_msg:
        result["error"] = job.error_msg
    return result


@app.get("/api/download/{job_id}")
async def download_result(job_id: str, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "done":
        raise HTTPException(400, f"Job not ready (status: {job.status})")
    if not job.result_path:
        raise HTTPException(500, "Result file not found")
    path = Path(job.result_path)
    if not path.exists():
        raise HTTPException(500, "Result file not found")
    media = {".pdf": "application/pdf", ".html": "text/html", ".zip": "application/zip"}
    return FileResponse(str(path), filename=path.name, media_type=media.get(path.suffix, "application/octet-stream"))


@app.delete("/api/cleanup/{job_id}")
async def cleanup_job(job_id: str, db: Session = Depends(get_db)):
    job = delete_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    work_dir = Path(job.work_dir)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    return {"deleted": job_id}
