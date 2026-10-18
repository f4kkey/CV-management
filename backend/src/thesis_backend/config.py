from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "CV Management API"
    app_debug: bool = False
    data_dir: Path = BACKEND_ROOT / "data"
    ocr_dpi: int = 200

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        extra="ignore",
    )
    
    database_url: str
    model_api_url: str = "http://127.0.0.1:8100"
    model_api_key: str
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str = "cv-files"
    minio_secure: bool = False


settings = Settings()
