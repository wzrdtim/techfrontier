from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from app.core.images import process_content_image, process_thumbnail_image
from app.core.storage import LocalStorage


def _png_bytes(width: int, height: int, color: tuple[int, int, int] = (20, 120, 110)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_content_image_resized_to_webp(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    saved = process_content_image(_png_bytes(2400, 1800), storage)
    assert saved.format == "WEBP"
    assert saved.url.endswith(".webp")
    assert saved.width <= 1600
    assert saved.height <= 1600
    webp_name = Path(saved.url).name
    assert (tmp_path / webp_name).exists()
    assert (tmp_path / webp_name.replace(".webp", ".avif")).exists()


def test_thumbnail_image_webp(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    saved = process_thumbnail_image(_png_bytes(2000, 1500), storage)
    assert saved.format == "WEBP"
    assert saved.url.endswith(".webp")
    assert saved.width <= 960
    assert saved.height <= 540
    assert saved.card_url and saved.card_url.endswith("-sm.webp")

    path = tmp_path / Path(saved.url).name
    card = tmp_path / Path(saved.card_url).name
    assert path.exists()
    assert card.exists()
    with Image.open(path) as image:
        assert image.format == "WEBP"
        assert image.mode == "RGB"
    with Image.open(card) as image:
        assert image.width <= 640
        assert image.height <= 400


def test_thumbnail_helpers_fallback_without_card(tmp_path: Path, monkeypatch):
    from app.core import images as images_mod
    from app.core.storage import LocalStorage

    storage = LocalStorage(tmp_path)
    monkeypatch.setattr(images_mod, "get_storage", lambda: storage)
    only = tmp_path / "solo.webp"
    only.write_bytes(b"not-a-real-image")
    url = "/static/uploads/solo.webp"
    assert images_mod.thumbnail_card_url(url) == url
    assert images_mod.thumbnail_srcset(url) == f"{url} 960w"


def test_thumbnail_helpers_with_cdn_url(monkeypatch):
    from app.core import images as images_mod

    class _CdnSettings:
        image_cdn_base = "https://images.techfrontier.se"

    monkeypatch.setattr(images_mod, "get_settings", lambda: _CdnSettings())

    url = "https://images.techfrontier.se/abcdef.webp"
    assert images_mod.thumbnail_card_url(url) == (
        "https://images.techfrontier.se/abcdef-sm.webp"
    )
    assert images_mod.thumbnail_srcset(url) == (
        "https://images.techfrontier.se/abcdef-sm.webp 640w, "
        "https://images.techfrontier.se/abcdef.webp 960w"
    )
