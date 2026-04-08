"""
api.py — FastAPI backend for the SLC Video Pipeline.
Receives batch webhooks from the Chrome extension, queues jobs in MySQL,
and processes them sequentially in the background.
"""

import logging
import shutil
import threading
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import add_job, get_pending_ids, get_queue
from core import process_single_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(title="SLC Video Pipeline API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("/tmp/slc_uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ── Request models ───────────────────────────────────────────────────────

class VideoData(BaseModel):
    course_name: str
    chapter_name: str
    video_url: str


class BatchPayload(BaseModel):
    videos: list[VideoData] = Field(..., max_length=6)


# ── Background worker (single-threaded, with re-check loop) ─────────────

_processing_lock = threading.Lock()


def _process_pending():
    """Process every pending job sequentially. Only one worker runs at a time."""
    if not _processing_lock.acquire(blocking=False):
        log.info("Background worker already running — skipping")
        return
    try:
        while True:
            pending = get_pending_ids()
            if not pending:
                break
            log.info("Background worker found %d pending jobs", len(pending))
            for job_id in pending:
                process_single_job(job_id)
        log.info("Background worker finished — no more pending jobs")
    finally:
        _processing_lock.release()


# ── Endpoints ────────────────────────────────────────────────────────────

@app.post("/api/process-batch")
def process_batch(payload: BatchPayload, background_tasks: BackgroundTasks):
    """Accept a batch of video URLs, insert into DB, kick off background processing."""
    job_ids = []
    for v in payload.videos:
        jid = add_job(
            course_name=v.course_name,
            unit_number=v.chapter_name,
            video_url=v.video_url,
        )
        job_ids.append(jid)
        log.info("Queued job %d: %s / %s", jid, v.course_name, v.chapter_name)

    background_tasks.add_task(_process_pending)

    return {"status": "ok", "queued": len(job_ids), "job_ids": job_ids}


@app.post("/api/upload-video")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    course_name: str = Form(...),
    chapter_name: str = Form(...),
):
    """Accept a direct video upload (for blob: URLs the browser can't send as a link).
    Saves to disk, creates a job with file:// URL, and starts processing."""
    file_path = UPLOAD_DIR / f"{uuid4().hex}.mp4"
    with open(file_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    jid = add_job(
        course_name=course_name,
        unit_number=chapter_name,
        video_url=f"file://{file_path}",
    )
    log.info("Upload job %d: %s / %s (%s)", jid, course_name, chapter_name, file_path.name)

    background_tasks.add_task(_process_pending)

    return {"status": "ok", "job_id": jid}


@app.get("/")
def root():
    return {"service": "SLC Video Pipeline API", "docs": "/docs"}


@app.get("/health")
def health():
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    ffprobe_ok = shutil.which("ffprobe") is not None
    return {
        "status": "ok" if (ffmpeg_ok and ffprobe_ok) else "degraded",
        "ffmpeg": ffmpeg_ok,
        "ffprobe": ffprobe_ok,
    }


@app.post("/api/retry-failed")
def retry_failed(background_tasks: BackgroundTasks):
    """Reset all failed jobs back to pending and reprocess."""
    from database import retry_all_failed
    count = retry_all_failed()
    if count > 0:
        background_tasks.add_task(_process_pending)
    return {"status": "ok", "retried": count}


@app.get("/api/jobs")
def list_jobs():
    """Debug endpoint — list all jobs in the database."""
    jobs = get_queue()
    return {"count": len(jobs), "jobs": jobs}
