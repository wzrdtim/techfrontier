from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from app.core.images import process_content_image, process_thumbnail_image


def _png_bytes(width: int, height: int, color: tuple[int, int, int] = (20, 120, 110)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_content_image_resized_to_webp(tmp_path: Path):
    saved = process_content_image(_png_bytes(2400, 1800), tmp_path)
    assert saved.format == "WEBP"
    assert saved.url.endswith(".webp")
    assert saved.width <= 1600
    assert saved.height <= 1600
    webp_name = Path(saved.url).name
    assert (tmp_path / webp_name).exists()
    assert (tmp_path / webp_name.replace(".webp", ".avif")).exists()


def test_thumbnail_image_webp(tmp_path: Path):
    saved = process_thumbnail_image(_png_bytes(2000, 1500), tmp_path)
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

    monkeypatch.setattr(images_mod, "UPLOAD_DIR", tmp_path)
    only = tmp_path / "solo.webp"
    only.write_bytes(b"not-a-real-image")
    url = "/static/uploads/solo.webp"
    assert images_mod.thumbnail_card_url(url) == url
    assert images_mod.thumbnail_srcset(url) == f"{url} 960w"
