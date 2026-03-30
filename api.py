"""
api.py — FastAPI backend for the SLC Video Pipeline.
Receives batch webhooks from the Chrome extension, queues jobs in MySQL,
and processes them sequentially in the background.
"""

import logging

from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel, Field

from database import add_job, get_pending_ids
from core import process_single_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(title="SLC Video Pipeline API")


# ── Request models ───────────────────────────────────────────────────────

class VideoData(BaseModel):
    course_name: str
    chapter_name: str
    video_url: str


class BatchPayload(BaseModel):
    videos: list[VideoData] = Field(..., max_length=6)


# ── Background worker ───────────────────────────────────────────────────

def _process_pending():
    """Process every pending job sequentially (one at a time)."""
    pending = get_pending_ids()
    log.info("Background worker starting: %d pending jobs", len(pending))
    for job_id in pending:
        process_single_job(job_id)
    log.info("Background worker finished")


# ── Endpoints ────────────────────────────────────────────────────────────

@app.post("/api/process-batch")
def process_batch(payload: BatchPayload, background_tasks: BackgroundTasks):
    """Accept a batch of videos, insert into DB, kick off background processing."""
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


@app.get("/health")
def health():
    return {"status": "ok"}
