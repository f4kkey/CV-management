"""API checks isolated from Neon, MinIO, and the host model server."""

from io import BytesIO
from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from thesis_backend.schemas.extraction import CvProfile
from thesis_backend import main
from thesis_backend.config import settings
from thesis_backend.database.session import Base
from thesis_backend.models import ExtractionJob  # noqa: F401
from thesis_backend.services import extraction, object_storage


class StoredResponse(BytesIO):
    def release_conn(self):
        pass


@pytest.fixture
def app_client(monkeypatch):
    data_dir = Path(__file__).parent / ".tmp" / uuid4().hex
    data_dir.mkdir(parents=True)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    files = {}

    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(extraction, "SessionLocal", session)
    monkeypatch.setattr(extraction.executor, "submit", lambda *args: None)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "initialize_bucket", lambda: None)
    monkeypatch.setattr(main, "shutdown", lambda: None)
    monkeypatch.setattr(
        object_storage,
        "upload_file",
        lambda source, object_key, content_type: files.__setitem__(object_key, source.read_bytes()),
    )
    monkeypatch.setattr(object_storage, "get_file", lambda key: StoredResponse(files[key]))
    monkeypatch.setattr(object_storage, "remove_file", lambda key: files.pop(key, None))

    with TestClient(main.app) as client:
        yield client, files, data_dir

    engine.dispose()
    shutil.rmtree(data_dir, ignore_errors=True)


def upload(client, name="cv.txt", content=b"JESSICA CLAIRE\nPython developer"):
    return client.post("/api/extractions", files={"file": (name, content, "text/plain")})


def test_upload_list_original_and_result(app_client, monkeypatch):
    client, files, data_dir = app_client
    response = upload(client)
    assert response.status_code == 202
    job = response.json()
    assert client.get(job["source_url"]).text == "JESSICA CLAIRE\nPython developer"
    assert len(client.get("/api/extractions").json()) == 1

    document = SimpleNamespace(
        pages=[SimpleNamespace(lines=["text"])],
        model_dump=lambda mode: {"pages": []},
    )

    def fake_extract(ident, source, reader_output):
        assert reader_output.exists()
        assert extraction.get_job(ident)["status"] == "extracting"
        return CvProfile.model_validate(
            {"personal_information": {"full_name": "JESSICA CLAIRE"}}
        )

    monkeypatch.setattr(extraction, "extract_document", lambda *args, **kwargs: document)
    monkeypatch.setattr(extraction, "extract_profile", fake_extract)
    extraction.process(job["id"], data_dir / job["id"] / "original.txt")

    result = client.get(f"/api/extractions/{job['id']}").json()
    assert result["status"] == "complete"
    assert result["profile"]["personal_information"]["full_name"] == "JESSICA CLAIRE"
    assert files


@pytest.mark.parametrize(
    ("name", "content", "status"),
    [("cv.exe", b"x", 415), ("cv.txt", b"", 400),
     ("cv.pdf", b"not a pdf", 400), ("cv.txt", b"\xff", 400)],
)
def test_invalid_uploads(app_client, name, content, status):
    client, files, data_dir = app_client
    assert upload(client, name, content).status_code == status
    assert files == {}
    assert list(data_dir.iterdir()) == []


def test_queue_limit(app_client):
    client, _, _ = app_client
    for _ in range(4):
        assert upload(client, content=b"CV").status_code == 202
    assert upload(client, content=b"CV").status_code == 429


def test_pipeline_failure_is_recorded(app_client, monkeypatch):
    client, _, data_dir = app_client
    job = upload(client, content=b"CV").json()
    monkeypatch.setattr(
        extraction,
        "extract_document",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad file")),
    )
    monkeypatch.setattr(extraction.logging, "exception", lambda *args: None)
    extraction.process(job["id"], data_dir / job["id"] / "original.txt")
    result = client.get(f"/api/extractions/{job['id']}").json()
    assert result["status"] == "failed"
    assert "profile" not in result
