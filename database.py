"""
database.py — Shared MySQL state for the SLC Video Pipeline.
Connection via SQLAlchemy + PyMySQL. All services (FastAPI + Streamlit) import this.
"""

import os
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Enum,
)
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_recycle=1800,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    course_name   = Column(String(255), nullable=False)
    unit_number   = Column(String(255), nullable=False)
    video_url     = Column(Text, nullable=False)
    status        = Column(
        Enum("pending", "processing", "done", "failed", name="job_status"),
        nullable=False,
        default="pending",
    )
    file_path     = Column(Text, nullable=True)
    onedrive_url  = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(engine)


# ── Helper functions ─────────────────────────────────────────────────────

def add_job(course_name: str, unit_number: str, video_url: str) -> int:
    """Insert a new pending job and return its id."""
    with SessionLocal() as session:
        job = Job(
            course_name=course_name,
            unit_number=unit_number,
            video_url=video_url,
            status="pending",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def update_status(
    job_id: int,
    status: str,
    file_path: str | None = None,
    onedrive_url: str | None = None,
    error_message: str | None = None,
):
    """Update a job's status and optional result fields."""
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = status
        if file_path is not None:
            job.file_path = file_path
        if onedrive_url is not None:
            job.onedrive_url = onedrive_url
        if error_message is not None:
            job.error_message = error_message
        session.commit()


def claim_job(job_id: int) -> bool:
    """Atomically claim a pending job for processing. Returns True if claimed."""
    with SessionLocal() as session:
        rows = (
            session.query(Job)
            .filter(Job.id == job_id, Job.status == "pending")
            .update({"status": "processing"})
        )
        session.commit()
        return rows > 0


def get_job(job_id: int) -> dict | None:
    """Return a single job as a dict, or None."""
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        if job is None:
            return None
        return _row_to_dict(job)


def get_queue() -> list[dict]:
    """Return all jobs ordered by created_at descending."""
    with SessionLocal() as session:
        rows = session.query(Job).order_by(Job.created_at.desc()).all()
        return [_row_to_dict(r) for r in rows]


def get_pending_ids() -> list[int]:
    """Return ids of all pending jobs (oldest first)."""
    with SessionLocal() as session:
        rows = (
            session.query(Job.id)
            .filter(Job.status == "pending")
            .order_by(Job.created_at.asc())
            .all()
        )
        return [r[0] for r in rows]


def clear_done():
    """Delete all jobs with status 'done'."""
    with SessionLocal() as session:
        session.query(Job).filter(Job.status == "done").delete()
        session.commit()


def retry_failed():
    """Reset all failed jobs back to pending."""
    with SessionLocal() as session:
        session.query(Job).filter(Job.status == "failed").update(
            {"status": "pending", "error_message": None}
        )
        session.commit()


def _row_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "course_name": job.course_name,
        "unit_number": job.unit_number,
        "video_url": job.video_url,
        "status": job.status,
        "file_path": job.file_path,
        "onedrive_url": job.onedrive_url,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }
