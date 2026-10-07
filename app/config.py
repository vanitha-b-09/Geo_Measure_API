"""Runtime configuration, overridable through environment variables."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./geo_measure.db")
    # Maximum size of the uploaded file itself.
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024
    # Zip-bomb protection: total uncompressed size and number of members.
    max_unzipped_bytes: int = int(os.getenv("MAX_UNZIPPED_MB", "500")) * 1024 * 1024
    max_zip_members: int = int(os.getenv("MAX_ZIP_MEMBERS", "200"))
    # Upper bound on features per file (processing is synchronous).
    max_features: int = int(os.getenv("MAX_FEATURES", "100000"))


settings = Settings()
