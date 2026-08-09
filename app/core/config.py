from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_database_url(url: str) -> str:
    """Render (and others) provide postgres://; SQLAlchemy+psycopg needs postgresql+psycopg://."""
    value = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if value.startswith(prefix):
            return "postgresql+psycopg://" + value[len(prefix) :]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/blog"
    secret_key: str = "change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    app_name: str = "Techfrontier"
    debug: bool = False
    admin_email: str = "admin@techfrontier.se"
    admin_username: str = "admin"
    admin_password: str = "admin"
    admin_cookie_name: str = "techfrontier_admin"
    auth_cookie_name: str = "techfrontier_auth"
    csrf_cookie_name: str = "techfrontier_csrf"
    visitor_cookie_name: str = "techfrontier_vid"
    site_url: str = "https://techfrontier.se"
    image_max_upload_bytes: int = 5 * 1024 * 1024
    image_max_width: int = 1600
    image_max_height: int = 1600
    image_webp_quality: int = 82
    image_avif_quality: int = 65
    thumbnail_max_width: int = 960
    thumbnail_max_height: int = 540
    thumbnail_card_max_width: int = 640
    thumbnail_card_max_height: int = 400
    social_facebook: str = ""
    social_twitter: str = ""
    social_linkedin: str = ""
    social_github: str = ""
    # Optional SMTP — when set, contact form messages are emailed to admin_email
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    # Cloudflare R2 (S3-compatible). When configured, uploads go to R2 instead of local disk.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_endpoint_url: str = ""
    image_public_base_url: str = ""  # e.g. https://images.techfrontier.se

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> object:
        if isinstance(value, str) and value:
            return _normalize_database_url(value)
        return value

    @property
    def cookie_secure(self) -> bool:
        return self.site_url.lower().startswith("https://")

    @property
    def mail_from(self) -> str:
        return (self.smtp_from or self.admin_email).strip()

    @property
    def r2_configured(self) -> bool:
        return bool(
            self.r2_account_id.strip()
            and self.r2_access_key_id.strip()
            and self.r2_secret_access_key.strip()
            and self.r2_bucket_name.strip()
            and self.image_public_base_url.strip()
        )

    @property
    def r2_endpoint(self) -> str:
        if self.r2_endpoint_url.strip():
            return self.r2_endpoint_url.strip().rstrip("/")
        account = self.r2_account_id.strip()
        return f"https://{account}.r2.cloudflarestorage.com"

    @property
    def image_cdn_base(self) -> str:
        return self.image_public_base_url.strip().rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
