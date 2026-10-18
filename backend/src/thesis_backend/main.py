from fastapi import FastAPI
from contextlib import asynccontextmanager
from thesis_backend.services.extraction import shutdown
from thesis_backend.api.health import router as health_router
from thesis_backend.config import settings
from thesis_backend.api.extractions import router as extractions_router
from thesis_backend.services.object_storage import initialize_bucket
from thesis_backend.database.session import Base, engine
from thesis_backend.models import ExtractionJob  # noqa: F401

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    initialize_bucket()
    yield
    shutdown()

app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    lifespan=lifespan,
)

app.include_router(health_router, prefix="/api")
app.include_router(extractions_router, prefix="/api")
