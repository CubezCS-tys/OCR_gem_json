"""
Database layer — SQLite (dev/default) or PostgreSQL (production).

Set DATABASE_URL in .env to switch:
  SQLite    (default):  not set, or  sqlite:///./scantotext.db
  Postgres  (prod):     postgresql://user:pass@host/dbname
             Railway/Render supply this automatically as DATABASE_URL.

Tables
------
users         — one row per email; tracks subscription, trial, usage
magic_tokens  — one-time login tokens (15-min TTL; verified = consumed)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Integer,
    String,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ── Engine ────────────────────────────────────────────────────────────────────
_DATABASE_URL = os.getenv("DATABASE_URL", "")

if _DATABASE_URL:
    # Heroku/Railway/Render sometimes supply postgres:// — SQLAlchemy needs postgresql://
    if _DATABASE_URL.startswith("postgres://"):
        _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(
        _DATABASE_URL,
        pool_pre_ping=True,   # detect dead connections
        pool_size=5,
        max_overflow=10,
        echo=False,
    )
    DB_PATH = None
else:
    DB_PATH = Path(__file__).parent / "scantotext.db"
    engine  = create_engine(
        f"sqlite:///{DB_PATH}",
        connect_args={"check_same_thread": False},
        echo=False,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# ── Models ────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id                    = Column(Integer, primary_key=True, index=True)
    email                 = Column(String, unique=True, index=True, nullable=False)

    # Subscription
    is_subscribed         = Column(Boolean, default=False)
    stripe_customer_id    = Column(String, default="")
    stripe_subscription_id = Column(String, default="")
    current_period_start  = Column(Float, default=0.0)
    current_period_end    = Column(Float, default=0.0)

    # Free trial
    is_trial              = Column(Boolean, default=False)
    trial_expires         = Column(Float, default=0.0)   # epoch seconds

    # Usage (resets monthly)
    pages_used            = Column(Integer, default=0)
    page_limit            = Column(Integer, default=0)
    period_start          = Column(Float, default=0.0)   # when current usage window began

    # Timestamps
    created_at            = Column(Float, default=time.time)

    # ── Computed helpers (not stored) ─────────────────────────────────────────
    @property
    def trial_active(self) -> bool:
        return bool(self.is_trial and self.trial_expires and time.time() < self.trial_expires)

    @property
    def is_active(self) -> bool:
        return bool(self.is_subscribed or self.trial_active)

    @property
    def pages_remaining(self) -> int:
        return max(0, (self.page_limit or 0) - (self.pages_used or 0))

    def can_process(self, page_count: int) -> bool:
        return self.is_active and self.pages_remaining >= page_count


class MagicToken(Base):
    __tablename__ = "magic_tokens"

    id         = Column(Integer, primary_key=True, index=True)
    token      = Column(String, unique=True, index=True, nullable=False)
    email      = Column(String, nullable=False)
    expires_at = Column(Float, nullable=False)   # epoch seconds
    used       = Column(Boolean, default=False)


class Job(Base):
    """Persistent job store — replaces the in-memory dict so multi-worker
    deployments share state via the DB instead of process memory."""
    __tablename__ = "jobs"

    job_id      = Column(String, primary_key=True, index=True)
    filename    = Column(String, nullable=False)
    file_size   = Column(Integer, default=0)
    page_count  = Column(Integer, default=0)
    work_dir    = Column(String, nullable=False)    # stored as string path
    status      = Column(String, default="uploaded") # uploaded|processing|done|error
    type        = Column(String, default=None)       # free|pro
    result_path = Column(String, default=None)       # string path, nullable
    results     = Column(String, default="{}")       # JSON-encoded dict
    error_msg   = Column(String, default=None)
    created_at  = Column(Float, default=time.time)


# ── Init ─────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables if they don't exist (safe to call on every startup)."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """Yield a DB session (use as FastAPI dependency or plain context manager)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── CRUD helpers ──────────────────────────────────────────────────────────────

def get_user(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.lower().strip()).first()


def get_or_create_user(db: Session, email: str) -> User:
    email = email.lower().strip()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, created_at=time.time())
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def consume_pages(db: Session, user: User, count: int) -> None:
    """Atomically increment pages_used — safe under concurrent requests."""
    db.execute(
        text("UPDATE users SET pages_used = pages_used + :n WHERE id = :id"),
        {"n": count, "id": user.id},
    )
    db.commit()
    db.refresh(user)


def save_magic_token(db: Session, token: str, email: str, ttl_seconds: int = 900) -> None:
    mt = MagicToken(token=token, email=email.lower().strip(), expires_at=time.time() + ttl_seconds)
    db.add(mt)
    db.commit()


# ── Job CRUD ─────────────────────────────────────────────────────────────────

def create_job(
    db: Session,
    job_id: str,
    filename: str,
    file_size: int,
    page_count: int,
    work_dir: str,
) -> Job:
    job = Job(
        job_id=job_id,
        filename=filename,
        file_size=file_size,
        page_count=page_count,
        work_dir=work_dir,
        created_at=time.time(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: str) -> Job | None:
    return db.query(Job).filter(Job.job_id == job_id).first()


def update_job(db: Session, job_id: str, **kwargs) -> Job | None:
    job = get_job(db, job_id)
    if not job:
        return None
    for key, val in kwargs.items():
        setattr(job, key, val)
    db.commit()
    db.refresh(job)
    return job


def delete_job(db: Session, job_id: str) -> Job | None:
    job = get_job(db, job_id)
    if job:
        db.delete(job)
        db.commit()
    return job


def get_jobs_older_than(db: Session, cutoff: float) -> list[Job]:
    return db.query(Job).filter(Job.created_at < cutoff).all()


# ── Magic token CRUD ──────────────────────────────────────────────────────────

def consume_magic_token(db: Session, token: str) -> str | None:
    """
    Verify and consume a magic token.
    Returns the email if valid; None otherwise.
    """
    mt = db.query(MagicToken).filter(MagicToken.token == token).first()
    if not mt:
        return None
    if mt.used:
        return None
    if time.time() > mt.expires_at:
        return None
    mt.used = True
    db.commit()
    return mt.email
