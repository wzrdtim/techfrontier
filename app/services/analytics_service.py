from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, joinedload

from app.models.page_view import PageView
from app.models.post import Post

VISITOR_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|facebookexternalhit|preview|wget|curl|python-requests|httpclient",
    re.I,
)

_SEARCH_HOSTS = {
    "google.",
    "bing.",
    "duckduckgo.",
    "yahoo.",
    "yandex.",
    "baidu.",
    "ecosia.",
}

_SOCIAL_HOSTS = {
    "twitter.",
    "x.com",
    "t.co",
    "facebook.",
    "fb.com",
    "instagram.",
    "linkedin.",
    "reddit.",
    "youtube.",
    "tiktok.",
    "pinterest.",
    "threads.",
}


@dataclass
class NamedCount:
    label: str
    count: int


@dataclass
class AnalyticsSummary:
    page_views: int
    unique_visitors: int
    article_views: int
    top_articles: list[tuple[Post, int]]
    traffic_sources: list[NamedCount]
    devices: list[NamedCount]
    countries: list[NamedCount]
    referrers: list[NamedCount]
    daily_views: list[NamedCount]


def classify_device(user_agent: str | None) -> str:
    ua = (user_agent or "").lower()
    if not ua:
        return "unknown"
    if _BOT_RE.search(ua):
        return "bot"
    if "ipad" in ua or ("android" in ua and "mobile" not in ua) or "tablet" in ua:
        return "tablet"
    if "mobi" in ua or "iphone" in ua or "android" in ua:
        return "mobile"
    return "desktop"


def is_bot(user_agent: str | None) -> bool:
    return classify_device(user_agent) == "bot"


def country_from_headers(headers) -> str:
    for key in (
        "cf-ipcountry",
        "cloudfront-viewer-country",
        "x-vercel-ip-country",
        "x-country-code",
    ):
        value = headers.get(key)
        if value and value.strip() and value.strip().upper() not in {"XX", "T1"}:
            return value.strip().upper()[:8]
    return "ZZ"


def parse_referrer(referrer: str | None, site_host: str | None) -> tuple[str | None, str | None, str]:
    if not referrer:
        return None, None, "direct"
    try:
        parsed = urlparse(referrer)
    except ValueError:
        return referrer[:1000], None, "referral"
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host:
        return referrer[:1000], None, "direct"
    if site_host and host == site_host.lower().removeprefix("www."):
        return referrer[:1000], host, "internal"
    for needle in _SEARCH_HOSTS:
        if needle in host or host.endswith(needle.rstrip(".")):
            return referrer[:1000], host, "search"
    for needle in _SOCIAL_HOSTS:
        if needle in host or host == needle.rstrip("."):
            return referrer[:1000], host, "social"
    return referrer[:1000], host, "referral"


def extract_post_slug(path: str) -> str | None:
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "posts" and parts[1]:
        return parts[1]
    return None


class AnalyticsService:
    @staticmethod
    def should_track(method: str, path: str, status_code: int, user_agent: str | None) -> bool:
        if method.upper() != "GET" or status_code >= 400:
            return False
        if is_bot(user_agent):
            return False
        clean = path.split("?", 1)[0]
        if clean in {"/robots.txt", "/sitemap.xml", "/health"}:
            return False
        for prefix in ("/admin", "/api", "/static", "/favicon"):
            if clean == prefix or clean.startswith(prefix + "/"):
                return False
        return True

    @staticmethod
    def record(
        db: Session,
        *,
        path: str,
        visitor_id: str,
        referrer: str | None,
        user_agent: str | None,
        country: str,
        site_host: str | None,
    ) -> PageView | None:
        clean_path = path.split("?", 1)[0][:500] or "/"
        if not AnalyticsService.should_track("GET", clean_path, 200, user_agent):
            return None

        ref, host, source = parse_referrer(referrer, site_host)
        device = classify_device(user_agent)
        post_id = None
        slug = extract_post_slug(clean_path)
        if slug:
            post = db.execute(select(Post.id).where(Post.slug == slug)).scalar_one_or_none()
            post_id = post

        view = PageView(
            path=clean_path,
            visitor_id=visitor_id[:64],
            referrer=ref,
            referrer_host=host,
            traffic_source=source,
            country=(country or "ZZ")[:8],
            device=device,
            user_agent=(user_agent or "")[:400] or None,
            post_id=post_id,
        )
        db.add(view)
        db.commit()
        db.refresh(view)
        return view

    @staticmethod
    def summary(db: Session, *, days: int = 30) -> AnalyticsSummary:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        page_views = db.execute(
            select(func.count()).select_from(PageView).where(PageView.created_at >= since)
        ).scalar_one()
        unique_visitors = db.execute(
            select(func.count(func.distinct(PageView.visitor_id))).where(
                PageView.created_at >= since
            )
        ).scalar_one()
        article_views = db.execute(
            select(func.count())
            .select_from(PageView)
            .where(PageView.created_at >= since, PageView.post_id.is_not(None))
        ).scalar_one()

        top_rows = db.execute(
            select(PageView.post_id, func.count().label("views"))
            .where(PageView.created_at >= since, PageView.post_id.is_not(None))
            .group_by(PageView.post_id)
            .order_by(desc("views"))
            .limit(8)
        ).all()
        top_articles: list[tuple[Post, int]] = []
        if top_rows:
            ids = [row[0] for row in top_rows]
            posts = {
                p.id: p
                for p in db.execute(
                    select(Post).options(joinedload(Post.tags)).where(Post.id.in_(ids))
                )
                .scalars()
                .unique()
                .all()
            }
            for post_id, views in top_rows:
                post = posts.get(post_id)
                if post is not None:
                    top_articles.append((post, int(views)))

        def group_counts(column, limit: int = 8) -> list[NamedCount]:
            rows = db.execute(
                select(column, func.count().label("c"))
                .where(PageView.created_at >= since)
                .group_by(column)
                .order_by(desc("c"))
                .limit(limit)
            ).all()
            return [NamedCount(label=str(label or "Unknown"), count=int(c)) for label, c in rows]

        traffic_sources = group_counts(PageView.traffic_source)
        devices = [
            NamedCount(label=item.label.title(), count=item.count)
            for item in group_counts(PageView.device)
            if item.label != "bot"
        ]
        countries = [
            NamedCount(
                label="Unknown" if label == "ZZ" else label,
                count=count,
            )
            for label, count in (
                (item.label, item.count) for item in group_counts(PageView.country)
            )
        ]
        referrer_rows = db.execute(
            select(PageView.referrer_host, func.count().label("c"))
            .where(
                PageView.created_at >= since,
                PageView.referrer_host.is_not(None),
                PageView.traffic_source != "internal",
            )
            .group_by(PageView.referrer_host)
            .order_by(desc("c"))
            .limit(8)
        ).all()
        referrers = [NamedCount(label=str(host), count=int(c)) for host, c in referrer_rows]

        # Daily views for sparkline-style list (last N days)
        day_expr = func.date(PageView.created_at)
        daily_rows = db.execute(
            select(day_expr.label("day"), func.count().label("c"))
            .where(PageView.created_at >= since)
            .group_by("day")
            .order_by("day")
        ).all()
        daily_views = [
            NamedCount(label=str(day), count=int(c)) for day, c in daily_rows
        ]

        return AnalyticsSummary(
            page_views=int(page_views or 0),
            unique_visitors=int(unique_visitors or 0),
            article_views=int(article_views or 0),
            top_articles=top_articles,
            traffic_sources=traffic_sources,
            devices=devices,
            countries=countries,
            referrers=referrers,
            daily_views=daily_views,
        )
