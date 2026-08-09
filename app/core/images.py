from __future__ import annotations

import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings
from app.core.storage import ObjectStorage, get_storage

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

# Kept for admin/media callers that still import the path constant.
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
    """Derive the card companion URL without breaking absolute https:// URLs."""
    if url.endswith(".webp") and not url.endswith("-sm.webp"):
        return f"{url[:-5]}-sm.webp"
    parts = urlsplit(url)
    path = Path(parts.path)
    card_path = f"{path.parent.as_posix().rstrip('/')}/{path.stem}-sm.webp"
    if not card_path.startswith("/"):
        card_path = "/" + card_path
    return urlunsplit((parts.scheme, parts.netloc, card_path, "", ""))


def _key_from_url(url: str) -> str | None:
    name = Path(urlsplit(url).path).name
    if not name or name in {".", ".."}:
        return None
    return name


def _variant_available(url: str, storage: ObjectStorage | None = None) -> bool:
    """True when the card/sibling object is expected to exist."""
    settings = get_settings()
    base = settings.image_cdn_base
    if base and url.startswith(base + "/"):
        # Thumbnails always upload a -sm companion to R2; avoid HEAD on every render.
        return True
    key = _key_from_url(url)
    if not key:
        return False
    store = storage or get_storage()
    return store.exists(key)


def thumbnail_srcset(url: str | None) -> str:
    """Build a srcset string for a stored thumbnail URL (full + card variant)."""
    if not url:
        return ""
    card = _card_url_for(url)
    if _variant_available(card):
        return f"{card} 640w, {url} 960w"
    return f"{url} 960w"


def thumbnail_card_url(url: str | None) -> str:
    """Prefer the card-sized companion; fall back to the full thumbnail URL."""
    if not url:
        return ""
    card = _card_url_for(url)
    if _variant_available(card):
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


def _webp_bytes(image: Image.Image, quality: int) -> bytes:
    buffer = BytesIO()
    _to_rgb(image).save(buffer, format="WEBP", quality=quality, method=6)
    return buffer.getvalue()


def _avif_bytes(image: Image.Image, quality: int) -> bytes | None:
    if not _AVIF_AVAILABLE:
        return None
    try:
        buffer = BytesIO()
        _to_rgb(image).save(buffer, format="AVIF", quality=quality)
        return buffer.getvalue()
    except (OSError, ValueError, KeyError):
        return None


def _store_image_variants(
    image: Image.Image,
    *,
    stem: str,
    storage: ObjectStorage,
    quality: int,
    avif_quality: int,
    card: Image.Image | None = None,
) -> SavedImage:
    webp_key = f"{stem}.webp"
    url = storage.put(webp_key, _webp_bytes(image, quality), "image/webp")

    avif_data = _avif_bytes(image, avif_quality)
    if avif_data is not None:
        storage.put(f"{stem}.avif", avif_data, "image/avif")

    card_url = None
    if card is not None:
        card_key = f"{stem}-sm.webp"
        card_url = storage.put(card_key, _webp_bytes(card, quality), "image/webp")

    return SavedImage(
        url=url,
        width=image.width,
        height=image.height,
        format="WEBP",
        card_url=card_url,
    )


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


def process_content_image(
    data: bytes,
    storage: ObjectStorage | None = None,
) -> SavedImage:
    """Resize and store editor/content images as WebP (+ AVIF sidecar when available)."""
    settings = get_settings()
    store = storage or get_storage()
    image = _fit_within(
        _load_image(data),
        settings.image_max_width,
        settings.image_max_height,
    )
    return _store_image_variants(
        image,
        stem=_unique_stem(),
        storage=store,
        quality=settings.image_webp_quality,
        avif_quality=settings.image_avif_quality,
    )


def process_thumbnail_image(
    data: bytes,
    storage: ObjectStorage | None = None,
) -> SavedImage:
    """Resize and store post thumbnails as WebP (+ card srcset variant)."""
    settings = get_settings()
    store = storage or get_storage()
    image = _fit_within(
        _load_image(data),
        settings.thumbnail_max_width,
        settings.thumbnail_max_height,
    )
    card = _fit_within(
        image,
        settings.thumbnail_card_max_width,
        settings.thumbnail_card_max_height,
    )
    return _store_image_variants(
        image,
        stem=_unique_stem(),
        storage=store,
        quality=settings.image_webp_quality,
        avif_quality=settings.image_avif_quality,
        card=card,
    )
