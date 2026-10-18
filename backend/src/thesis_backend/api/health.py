from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from thesis_backend.database.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok"}

@router.get("/health/database")
def database_health(
    database: Session = Depends(get_db),
):
    database.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected",
    }
