from pathlib import Path

import httpx

from thesis_backend.schemas.extraction import CvProfile
from thesis_backend.config import settings


def extract_profile(
    ident: str,
    source: Path,
    reader_output: Path,
) -> CvProfile:
    with source.open("rb") as source_file, reader_output.open("rb") as reader_file:
        response = httpx.post(
            f"{settings.model_api_url}/extract",
            data={"ident": ident},
            files={
                "source": (source.name, source_file),
                "reader": (reader_output.name, reader_file, "application/json"),
            },
            headers={"X-Model-Key": settings.model_api_key},
            timeout=660,
        )

    response.raise_for_status()
    return CvProfile.model_validate(response.json())
