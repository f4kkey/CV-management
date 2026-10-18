import shutil
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from thesis_backend.services import object_storage
from thesis_backend.config import settings
from thesis_backend.services import extraction as extraction_service

router = APIRouter(
    prefix="/extractions",
    tags=["extractions"]
)

MAX_BYTES = 25 * 1024 * 1024


@router.get("")
def list_jobs():
    return extraction_service.list_jobs()


@router.post("", status_code=202)
async def upload(file: UploadFile):
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in {'.pdf', '.txt', '.md'}:
        await file.close()
        raise HTTPException(415, 'Choose a PDF, TXT or Markdown file.')
    ident = uuid4().hex
    folder = settings.data_dir / ident
    folder.mkdir(parents=True)
    source = folder / f"original{suffix}"
    object_key = f"extractions/{ident}/original{suffix}"
    try:
        size = 0
        with source.open('wb') as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, 'Maximum file size is 25 MB.')
                handle.write(chunk)
        if not size:
            raise HTTPException(400, 'The file is empty.')
        if suffix == '.pdf':
            with source.open('rb') as handle:
                if b'%PDF-' not in handle.read(1024):
                    raise HTTPException(400, 'This file does not look like a PDF.')
        else:
            try:
                source.read_text(encoding='utf-8-sig')
            except UnicodeError:
                raise HTTPException(400, 'Text files must use UTF-8 encoding.')

        job = extraction_service.create_job(
            ident=ident,
            filename=Path(file.filename).name,
            object_key=object_key,
        )

        if job is None:
            raise HTTPException(
                429,
                "The extraction queue is full. Please try again shortly.",
            )
        content_type = (
            "application/pdf"
            if suffix == ".pdf"
            else "text/plain"
        )

        object_storage.upload_file(
            source=source,
            object_key=object_key,
            content_type=content_type,
        )
        extraction_service.start_job(ident, source)

        return job
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        object_storage.remove_file(object_key)
        extraction_service.remove_job(ident)
        raise
    finally:
        await file.close()


@router.get("/{ident}")
def get_job(ident: str):
    try:
        UUID(ident)
    except ValueError:
        raise HTTPException(404, 'Extraction not found.')
    job = extraction_service.get_job(ident)

    if job is None:
        raise HTTPException(404, "Extraction not found.",)
    return job


@router.get("/{ident}/original")
def original(ident: str):
    file_info = extraction_service.get_file_info(ident)

    if file_info is None:
        raise HTTPException(404, "Extraction not found.")

    object_key, filename = file_info
    response = object_storage.get_file(object_key)

    def stream():
        try:
            while chunk := response.read(1024 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    media_type = (
        "application/pdf"
        if filename.lower().endswith(".pdf")
        else "text/plain"
    )

    return StreamingResponse(
        stream(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
