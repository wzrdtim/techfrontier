from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

from app.core.config import get_settings

_TAG_RE = re.compile(r"<[^>]+>")


def absolute_url(path: str) -> str:
    base = get_settings().site_url.rstrip("/") + "/"
    return urljoin(base, path.lstrip("/"))


def truncate_meta(text: str | None, limit: int = 155) -> str:
    value = unescape(_TAG_RE.sub(" ", text or ""))
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def default_meta(
    *,
    title: str,
    description: str,
    path: str = "/",
    image: str | None = None,
    type: str = "website",
    robots: str = "index,follow",
) -> dict[str, Any]:
    settings = get_settings()
    image_url = absolute_url(image) if image else None
    return {
        "meta_title": title,
        "meta_description": truncate_meta(description),
        "canonical_url": absolute_url(path),
        "og_type": type,
        "og_image": image_url,
        "robots": robots,
        "site_name": settings.app_name,
        "site_url": settings.site_url.rstrip("/"),
    }
