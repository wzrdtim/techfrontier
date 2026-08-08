from __future__ import annotations

import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings

try:
    from pillow_heif import register_avif_opener, register_heif_opener

    register_heif_opener()
    register_avif_opener()
    _AVIF_AVAILABLE = True
except ImportError:  # pragma: no cover - optional at import time
    _AVIF_AVAILABLE = False

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/avif",
    "image/heic",
    "image/heif",
}

ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".avif",
    ".heic",
    ".heif",
}


UPLOAD_DIR = (
    Path(__file__).resolve().parents[2] / "frontend" / "static" / "uploads"
)


@dataclass(frozen=True)
class SavedImage:
    url: str
    width: int
    height: int
    format: str
    card_url: str | None = None


def _card_url_for(url: str) -> str:
    path = Path(url)
    return f"{path.parent}/{path.stem}-sm.webp"


def _upload_exists(url: str) -> bool:
    name = Path(url).name
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        return False
    return (UPLOAD_DIR / name).is_file()


def thumbnail_srcset(url: str | None) -> str:
    """Build a srcset string for a stored thumbnail URL (full + card variant)."""
    if not url:
        return ""
    card = _card_url_for(url)
    if _upload_exists(card):
        return f"{card} 640w, {url} 960w"
    return f"{url} 960w"


def thumbnail_card_url(url: str | None) -> str:
    """Prefer the card-sized companion; fall back to the full thumbnail URL."""
    if not url:
        return ""
    card = _card_url_for(url)
    if _upload_exists(card):
        return card
    return url


def _validate_upload_meta(file: UploadFile) -> None:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    suffix = Path(file.filename).suffix.lower()
    if suffix and suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    content_type = (file.content_type or "").lower()
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type")


def _load_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(BytesIO(data))
        image.load()
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="Invalid image file") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Could not read image") from exc
    return ImageOps.exif_transpose(image)


def _fit_within(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    fitted = image.copy()
    fitted.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return fitted


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


def _unique_stem() -> str:
    return uuid.uuid4().hex


def _write_webp(image: Image.Image, path: Path, quality: int) -> None:
    rgb = _to_rgb(image)
    rgb.save(path, format="WEBP", quality=quality, method=6)


def _write_avif(image: Image.Image, path: Path, quality: int) -> bool:
    if not _AVIF_AVAILABLE:
        return False
    try:
        rgb = _to_rgb(image)
        rgb.save(path, format="AVIF", quality=quality)
        return True
    except (OSError, ValueError, KeyError):
        return False


async def read_upload_bytes(file: UploadFile) -> bytes:
    settings = get_settings()
    _validate_upload_meta(file)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.image_max_upload_bytes:
        limit_mb = settings.image_max_upload_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"Image must be {limit_mb}MB or smaller",
        )
    return data


def process_content_image(data: bytes, upload_dir: Path) -> SavedImage:
    """Resize and store editor/content images as WebP (+ AVIF sidecar when available)."""
    settings = get_settings()
    upload_dir.mkdir(parents=True, exist_ok=True)

    image = _fit_within(
        _load_image(data),
        settings.image_max_width,
        settings.image_max_height,
    )
    stem = _unique_stem()
    webp_path = upload_dir / f"{stem}.webp"
    _write_webp(image, webp_path, settings.image_webp_quality)

    avif_path = upload_dir / f"{stem}.avif"
    _write_avif(image, avif_path, settings.image_avif_quality)

    return SavedImage(
        url=f"/static/uploads/{webp_path.name}",
        width=image.width,
        height=image.height,
        format="WEBP",
    )


def process_thumbnail_image(data: bytes, upload_dir: Path) -> SavedImage:
    """Resize and store post thumbnails as WebP (+ card srcset variant)."""
    settings = get_settings()
    upload_dir.mkdir(parents=True, exist_ok=True)

    image = _fit_within(
        _load_image(data),
        settings.thumbnail_max_width,
        settings.thumbnail_max_height,
    )
    stem = _unique_stem()
    webp_path = upload_dir / f"{stem}.webp"
    _write_webp(image, webp_path, settings.image_webp_quality)

    avif_path = upload_dir / f"{stem}.avif"
    _write_avif(image, avif_path, settings.image_avif_quality)

    card = _fit_within(
        image,
        settings.thumbnail_card_max_width,
        settings.thumbnail_card_max_height,
    )
    card_path = upload_dir / f"{stem}-sm.webp"
    _write_webp(card, card_path, settings.image_webp_quality)

    return SavedImage(
        url=f"/static/uploads/{webp_path.name}",
        width=image.width,
        height=image.height,
        format="WEBP",
        card_url=f"/static/uploads/{card_path.name}",
    )
