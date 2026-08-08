from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def cookie_secure(self) -> bool:
        return self.site_url.lower().startswith("https://")

    @property
    def mail_from(self) -> str:
        return (self.smtp_from or self.admin_email).strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
