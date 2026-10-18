import hashlib
import json
import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from thesis_backend.config import settings
from thesis_backend.services.document_reader import extract_document

from sqlalchemy import func, select

from thesis_backend.models import ExtractionJob
from thesis_backend.database.session import SessionLocal
from thesis_backend.services.model_client import extract_profile

ACTIVE_STATUSES = {"queued", "reading", "extracting"}
MAX_ACTIVE_JOBS = 4

queue_lock = Lock()
executor = ThreadPoolExecutor(max_workers=1)


def source_hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)

def get_file_info(ident: str) -> tuple[str, str] | None:
    with SessionLocal() as db:
        job = db.get(ExtractionJob, ident)

        if job is None:
            return None

        return job.object_key, job.filename

def job_to_dict(job: ExtractionJob) -> dict:
    result = {
        "id": job.id,
        "filename": job.filename,
        "status": job.status,
        "source_url": f"/api/extractions/{job.id}/original",
    }

    if job.profile is not None:
        result["profile"] = job.profile

    if job.error is not None:
        result["error"] = job.error

    if job.seconds is not None:
        result["seconds"] = job.seconds

    return result

def create_job(
    ident: str,
    filename: str,
    object_key: str,
) -> dict | None:
    with queue_lock:
        with SessionLocal() as db:
            active_jobs = db.scalar(
                select(func.count(ExtractionJob.id)).where(
                    ExtractionJob.status.in_(ACTIVE_STATUSES)
                )
            ) or 0

            if active_jobs >= MAX_ACTIVE_JOBS:
                return None

            job = ExtractionJob(
                id=ident,
                filename=filename,
                object_key=object_key,
                status="queued",
            )

            db.add(job)
            db.commit()
            db.refresh(job)

            return job_to_dict(job)


def get_job(ident: str) -> dict | None:
    with SessionLocal() as db:
        job = db.get(ExtractionJob, ident)

        if job is None:
            return None

        return job_to_dict(job)


def list_jobs() -> list[dict]:
    with SessionLocal() as db:
        jobs = db.scalars(
            select(ExtractionJob)
            .order_by(ExtractionJob.created_at.desc())
            .limit(100)
        ).all()

        return [job_to_dict(job) for job in jobs]


def remove_job(ident: str) -> None:
    with SessionLocal() as db:
        job = db.get(ExtractionJob, ident)

        if job is not None:
            db.delete(job)
            db.commit()


def update_job(ident: str, **values) -> None:
    with SessionLocal() as db:
        job = db.get(ExtractionJob, ident)

        if job is None:
            return

        for field, value in values.items():
            setattr(job, field, value)

        db.commit()


def start_job(ident: str, source: Path) -> None:
    executor.submit(process, ident, source)


def process(ident: str, source: Path) -> None:
    started_at = time.monotonic()
    folder = source.parent

    try:
        update_job(ident, status="reading")

        document = extract_document(
            source,
            ocr_dpi=settings.ocr_dpi,
        )

        if not any(page.lines for page in document.pages):
            raise ValueError(
                "The reader found no usable text in this file."
            )

        reader_output = folder / "reader" / f"{ident}.json"
        save_json(
            reader_output,
            {
                "status": "ok",
                "identity": {
                    "source": source_hash(source),
                },
                "document": document.model_dump(mode="json"),
            },
        )

        update_job(ident, status="extracting")

        profile = extract_profile(ident, source, reader_output)

        update_job(
            ident,
            status="complete",
            profile=profile.model_dump(mode="json"),
            seconds=round(time.monotonic() - started_at, 2),
        )

    except Exception:
        logging.exception(
            "Extraction failed for upload %s",
            ident,
        )

        update_job(
            ident,
            status="failed",
            error=(
                "Extraction failed. "
                "Check the backend terminal for details."
            ),
            seconds=round(time.monotonic() - started_at, 2),
        )

    finally:
        shutil.rmtree(folder, ignore_errors=True)


def shutdown() -> None:
    executor.shutdown(
        wait=False,
        cancel_futures=True,
    )
