from __future__ import annotations

import html
import re
from typing import Dict, List

import bleach
from bleach.css_sanitizer import CSSSanitizer

_IMAGE_BLOCK = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)$")

ALLOWED_TAGS = [
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "span",
    "a",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "blockquote",
    "pre",
    "code",
    "img",
    "figure",
    "figcaption",
    "div",
]

ALLOWED_ATTRIBUTES = {
    "*": ["style", "class"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
}

CSS_SANITIZER = CSSSanitizer(
    allowed_css_properties=[
        "color",
        "background-color",
        "font-size",
        "font-weight",
        "font-style",
        "text-decoration",
        "text-align",
    ]
)


def content_blocks(content: str) -> List[Dict[str, str]]:
    """Legacy plain-text / markdown-image splitter."""
    blocks: List[Dict[str, str]] = []
    for part in (content or "").split("\n\n"):
        part = part.strip()
        if not part:
            continue
        match = _IMAGE_BLOCK.match(part)
        if match:
            blocks.append(
                {
                    "type": "image",
                    "alt": match.group(1) or "",
                    "src": match.group(2),
                }
            )
        else:
            blocks.append({"type": "text", "text": part})
    return blocks


def looks_like_html(content: str) -> bool:
    value = (content or "").lstrip().lower()
    return value.startswith("<") or "<p" in value or "<div" in value or "<h" in value


def sanitize_html(content: str) -> str:
    return bleach.clean(
        content or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        css_sanitizer=CSS_SANITIZER,
        strip=True,
    )


def render_content_html(content: str) -> str:
    """Return safe HTML for article bodies (supports legacy markdown blocks)."""
    raw = content or ""
    if looks_like_html(raw):
        return sanitize_html(raw)

    parts: List[str] = []
    for block in content_blocks(raw):
        if block["type"] == "image":
            alt = html.escape(block.get("alt") or "")
            src = html.escape(block.get("src") or "", quote=True)
            caption = (
                f'<figcaption class="mt-2 text-sm text-muted">{alt}</figcaption>'
                if alt
                else ""
            )
            parts.append(
                f'<figure class="overflow-hidden rounded-xl">'
                f'<img src="{src}" alt="{alt}" class="w-full object-cover" />'
                f"{caption}"
                f"</figure>"
            )
        else:
            parts.append(f"<p>{html.escape(block['text'])}</p>")
    return "\n".join(parts)
