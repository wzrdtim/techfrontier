from __future__ import annotations

import math
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.types import Scope
from sqlalchemy.orm import Session

from app.api.routes import admin, auth, newsletter, posts
from app.core import database as database
from app.core.captcha import create_math_captcha, verify_math_captcha
from app.core.config import get_settings
from app.core.content import render_content_html
from app.core.database import get_db
from app.core.exceptions import AdminLoginRequired
from app.core.images import thumbnail_card_url, thumbnail_srcset
from app.core.mail import notify_admin_of_contact
from app.core.seo import absolute_url, default_meta, truncate_meta
from app.services.analytics_service import (
    VISITOR_COOKIE_MAX_AGE,
    AnalyticsService,
    country_from_headers,
)
from app.services.auth_service import AuthService
from app.services.comment_service import CommentService
from app.services.contact_service import ContactService
from app.services.post_service import PostService, plain_excerpt
from app.services.tag_service import TagService

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
POSTS_PER_PAGE = 9
COMMENT_SUCCESS_MESSAGE = (
    "Tack! Din kommentar har skickats in och väntar på granskning."
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db = database.SessionLocal()
    try:
        AuthService.ensure_admin_user(db)
        TagService.ensure_default_tags(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

(FRONTEND_DIR / "static" / "uploads").mkdir(parents=True, exist_ok=True)


class CachedStaticFiles(StaticFiles):
    """Serve static assets with browser-friendly Cache-Control headers.

    Uploads use UUID filenames, so they can be cached immutably for a year.
    CSS/JS and other assets get a shorter public cache.
    """

    def file_response(
        self,
        full_path,
        stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        path = scope.get("path", "")
        if "/uploads/" in path:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response


app.mount(
    "/static",
    CachedStaticFiles(directory=FRONTEND_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(directory=FRONTEND_DIR / "templates")
templates.env.globals["render_content_html"] = render_content_html
templates.env.globals["absolute_url"] = absolute_url
templates.env.globals["site_url"] = settings.site_url.rstrip("/")
templates.env.globals["site_name"] = settings.app_name
templates.env.globals["contact_email"] = settings.admin_email
templates.env.filters["thumbnail_srcset"] = thumbnail_srcset
templates.env.filters["thumbnail_card"] = thumbnail_card_url
templates.env.filters["plain_excerpt"] = plain_excerpt

app.include_router(auth.router, prefix="/api")
app.include_router(posts.router, prefix="/api")
app.include_router(newsletter.router, prefix="/api")
app.include_router(admin.router)


@app.middleware("http")
async def track_page_views(request: Request, call_next):
    response = await call_next(request)
    try:
        path = request.url.path
        user_agent = request.headers.get("user-agent")
        if not AnalyticsService.should_track(
            request.method,
            path,
            response.status_code,
            user_agent,
        ):
            return response

        visitor_id = request.cookies.get(settings.visitor_cookie_name)
        set_cookie = False
        if not visitor_id:
            visitor_id = uuid.uuid4().hex
            set_cookie = True

        site_host = urlparse(settings.site_url).hostname
        db = database.SessionLocal()
        try:
            AnalyticsService.record(
                db,
                path=path,
                visitor_id=visitor_id,
                referrer=request.headers.get("referer"),
                user_agent=user_agent,
                country=country_from_headers(request.headers),
                site_host=site_host,
            )
        finally:
            db.close()

        if set_cookie:
            response.set_cookie(
                key=settings.visitor_cookie_name,
                value=visitor_id,
                httponly=True,
                secure=settings.cookie_secure,
                samesite="lax",
                max_age=VISITOR_COOKIE_MAX_AGE,
                path="/",
            )
    except Exception:
        # Analytics must never break page responses.
        pass
    return response


def page_context(request: Request, **extra: object) -> dict:
    ctx: dict = {
        "request": request,
        "app_name": settings.app_name,
        "site_url": settings.site_url.rstrip("/"),
        "site_name": settings.app_name,
        "social_links": [
            item
            for item in [
                {"label": "Facebook", "href": settings.social_facebook, "icon": "facebook"},
                {"label": "X", "href": settings.social_twitter, "icon": "twitter"},
                {"label": "LinkedIn", "href": settings.social_linkedin, "icon": "linkedin"},
                {"label": "GitHub", "href": settings.social_github, "icon": "github"},
            ]
            if item["href"]
        ],
    }
    ctx.update(extra)
    return ctx


def build_page_items(current: int, total_pages: int) -> List:
    """Return page numbers and ellipsis markers for pagination UI."""
    if total_pages <= 7:
        return list(range(1, total_pages + 1))

    items = [1]
    if current > 3:
        items.append("…")

    start = max(2, current - 1)
    end = min(total_pages - 1, current + 1)
    for page in range(start, end + 1):
        if page not in items:
            items.append(page)

    if current < total_pages - 2:
        items.append("…")
    if total_pages not in items:
        items.append(total_pages)
    return items


def _looks_like_email(value: str) -> bool:
    return "@" in value and "." in value.split("@")[-1]


def _pagination(page: int, total: int) -> tuple[int, int, list]:
    total_pages = max(1, math.ceil(total / POSTS_PER_PAGE)) if total else 1
    current = min(page, total_pages)
    return current, total_pages, build_page_items(current, total_pages)


@app.exception_handler(AdminLoginRequired)
async def admin_login_required_handler(
    request: Request,
    exc: AdminLoginRequired,
) -> RedirectResponse:
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    total_pages = 1
    featured = PostService.get_featured(db, limit=2)
    posts_list, total = PostService.list_posts(
        db,
        skip=(page - 1) * POSTS_PER_PAGE,
        limit=POSTS_PER_PAGE,
        published_only=True,
    )
    if total > 0:
        total_pages = max(1, math.ceil(total / POSTS_PER_PAGE))
    if page > total_pages:
        page = total_pages
        posts_list, total = PostService.list_posts(
            db,
            skip=(page - 1) * POSTS_PER_PAGE,
            limit=POSTS_PER_PAGE,
            published_only=True,
        )

    path = "/" if page == 1 else f"/?page={page}"
    meta = default_meta(
        title=f"{settings.app_name} — Signal | AI, teknologi och framtidens idéer",
        description=(
            f"Tankar, analyser och idéer om AI och teknologi. Utforska tekniken, företagen och innovationerna som formar vår framtid. "
    
        ),
        path=path,
    )
    return templates.TemplateResponse(
        request,
        "index.html",
        page_context(
            request,
            featured=featured,
            posts=posts_list,
            total=total,
            page=page,
            total_pages=total_pages,
            page_items=build_page_items(page, total_pages),
            active_nav="articles",
            **meta,
        ),
    )


@app.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    query = " ".join(q.split())
    if not query:
        return RedirectResponse(url="/#articles", status_code=status.HTTP_303_SEE_OTHER)

    total_pages = 1
    posts_list, total = PostService.search_posts(
        db,
        query,
        skip=(page - 1) * POSTS_PER_PAGE,
        limit=POSTS_PER_PAGE,
        published_only=True,
    )
    if total > 0:
        total_pages = max(1, math.ceil(total / POSTS_PER_PAGE))
    if page > total_pages:
        page = total_pages
        posts_list, total = PostService.search_posts(
            db,
            query,
            skip=(page - 1) * POSTS_PER_PAGE,
            limit=POSTS_PER_PAGE,
            published_only=True,
        )

    from urllib.parse import quote_plus

    path = f"/search?q={quote_plus(query)}"
    if page > 1:
        path = f"{path}&page={page}"

    meta = default_meta(
        title=f'Search “{query}” — {settings.app_name}',
        description=f"Search results for “{query}” on {settings.app_name}.",
        path=path,
        robots="noindex,follow",
    )
    return templates.TemplateResponse(
        request,
        "search.html",
        page_context(
            request,
            query=query,
            posts=posts_list,
            total=total,
            page=page,
            total_pages=total_pages,
            page_items=build_page_items(page, total_pages),
            active_nav="articles",
            **meta,
        ),
    )


@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request) -> HTMLResponse:
    description = (
        f"{settings.app_name} är en stillsam plats för essäer och anteckningar "
        "om hur teknik faktiskt tar plats i världen."
    )
    meta = default_meta(
        title=f"Om — {settings.app_name}",
        description=description,
        path="/about",
    )
    return templates.TemplateResponse(
        request,
        "about.html",
        page_context(request, active_nav="about", **meta),
    )


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request) -> HTMLResponse:
    description = (
        f"How {settings.app_name} handles the information you share with us — "
        "including newsletter signups and contact messages."
    )
    meta = default_meta(
        title=f"Privacy Policy — {settings.app_name}",
        description=description,
        path="/privacy",
    )
    return templates.TemplateResponse(
        request,
        "privacy.html",
        page_context(request, active_nav=None, **meta),
    )


def _contact_page_context(
    request: Request,
    *,
    captcha_question: str,
    captcha_token: str,
    error: str | None = None,
    success: bool = False,
    form_email: str = "",
    form_subject: str = "",
    form_body: str = "",
) -> dict:
    lead = f"Send a message to the {settings.app_name} team."
    meta = default_meta(
        title=f"Contact — {settings.app_name}",
        description=lead,
        path="/contact",
    )
    return page_context(
        request,
        active_nav="contact",
        captcha_question=captcha_question,
        captcha_token=captcha_token,
        error=error,
        success=success,
        form_email=form_email,
        form_subject=form_subject,
        form_body=form_body,
        **meta,
    )


@app.get("/contact", response_class=HTMLResponse)
def contact_page(
    request: Request,
    sent: int | None = Query(None),
) -> HTMLResponse:
    captcha_question, captcha_token = create_math_captcha()
    return templates.TemplateResponse(
        request,
        "contact.html",
        _contact_page_context(
            request,
            captcha_question=captcha_question,
            captcha_token=captcha_token,
            success=bool(sent),
        ),
    )


@app.post("/contact", response_class=HTMLResponse)
def contact_submit(
    request: Request,
    email: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    captcha_question, new_token = create_math_captcha()
    context = _contact_page_context(
        request,
        captcha_question=captcha_question,
        captcha_token=new_token,
        form_email=email,
        form_subject=subject,
        form_body=body,
    )

    if not verify_math_captcha(captcha_token, captcha_answer):
        context["error"] = "CAPTCHA-svaret var fel. Försök igen."
        return templates.TemplateResponse(request, "contact.html", context, status_code=400)

    if not email.strip() or not subject.strip() or not body.strip():
        context["error"] = "E-post, ämne och meddelande krävs."
        return templates.TemplateResponse(request, "contact.html", context, status_code=400)

    if not _looks_like_email(email):
        context["error"] = "Ange en giltig e-postadress."
        return templates.TemplateResponse(request, "contact.html", context, status_code=400)

    ContactService.create(
        db,
        email=email,
        subject=subject,
        body=body,
    )
    notify_admin_of_contact(
        sender_email=email,
        subject=subject,
        body=body,
    )
    return RedirectResponse(
        url="/contact?sent=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/ai", response_class=HTMLResponse)
def ai_page(
    request: Request,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _tag_listing_page(
        request,
        db,
        page=page,
        tag_slug="ai",
        active_nav="ai",
        eyebrow="AI",
        page_title="Idéer om artificiell intelligens",
        lead="Artiklar taggade AI — modeller, produkter och praktiska lärdomar.",
        path="/ai",
    )


@app.get("/technology", response_class=HTMLResponse)
def technology_page(
    request: Request,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _tag_listing_page(
        request,
        db,
        page=page,
        tag_slug="technology",
        active_nav="technology",
        eyebrow="Teknologi",
        page_title="Anteckningar om modern teknik",
        lead="Artiklar taggade Teknologi — plattformar, verktyg och avvägningar.",
        path="/technology",
    )


@app.get("/analys", response_class=HTMLResponse)
def analys_page(
    request: Request,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _tag_listing_page(
        request,
        db,
        page=page,
        tag_slug="analys",
        active_nav="analys",
        eyebrow="Analys",
        page_title="Analyser och fördjupningar",
        lead="Artiklar taggade Analys — idéer, bolag och utvecklingar värda att förstå på djupet.",
        path="/analys",
    )


def _tag_listing_page(
    request: Request,
    db: Session,
    *,
    page: int,
    tag_slug: str,
    active_nav: str,
    eyebrow: str,
    page_title: str,
    lead: str,
    path: str,
) -> HTMLResponse:
    posts_list, total = PostService.list_posts(
        db,
        skip=(page - 1) * POSTS_PER_PAGE,
        limit=POSTS_PER_PAGE,
        published_only=True,
        tag_slug=tag_slug,
    )
    current, total_pages, page_items = _pagination(page, total)
    if current != page and total:
        posts_list, total = PostService.list_posts(
            db,
            skip=(current - 1) * POSTS_PER_PAGE,
            limit=POSTS_PER_PAGE,
            published_only=True,
            tag_slug=tag_slug,
        )
    meta = default_meta(
        title=f"{eyebrow} — {settings.app_name}",
        description=lead,
        path=path if current == 1 else f"{path}?page={current}",
    )
    return templates.TemplateResponse(
        request,
        "tag.html",
        page_context(
            request,
            active_nav=active_nav,
            eyebrow=eyebrow,
            page_title=page_title,
            lead=lead,
            posts=posts_list,
            total=total,
            page=current,
            total_pages=total_pages,
            page_items=page_items,
            pagination_base=path,
            **meta,
        ),
    )


@app.get("/posts/{slug}", response_class=HTMLResponse)
def post_detail(
    slug: str,
    request: Request,
    commented: int | None = Query(None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    post = PostService.get_by_slug(db, slug)
    if post is None or not PostService.is_live(post):
        meta = default_meta(
            title=f"Not found — {settings.app_name}",
            description="The article you asked for could not be found.",
            path=f"/posts/{slug}",
            robots="noindex,follow",
        )
        return templates.TemplateResponse(
            request,
            "post.html",
            page_context(
                request,
                post=None,
                not_found=True,
                active_nav="articles",
                **meta,
            ),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    PostService.record_view(db, post)
    captcha_question, captcha_token = create_math_captcha()
    comments = CommentService.list_for_post(db, post.id)
    description = truncate_meta(post.excerpt or post.content)
    meta = default_meta(
        title=f"{post.title} — {settings.app_name}",
        description=description or f"Read {post.title} on {settings.app_name}.",
        path=f"/posts/{post.slug}",
        image=post.thumbnail,
        type="article",
    )
    return templates.TemplateResponse(
        request,
        "post.html",
        page_context(
            request,
            post=post,
            comments=comments,
            captcha_question=captcha_question,
            captcha_token=captcha_token,
            comment_error=None,
            comment_success=COMMENT_SUCCESS_MESSAGE if commented else None,
            form_name="",
            form_email="",
            form_body="",
            not_found=False,
            active_nav="articles",
            **meta,
        ),
    )


@app.post("/posts/{slug}/comments", response_class=HTMLResponse)
def create_comment(
    slug: str,
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    body: str = Form(...),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    post = PostService.get_by_slug(db, slug)
    if post is None or not PostService.is_live(post):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    captcha_question, new_token = create_math_captcha()
    comments = CommentService.list_for_post(db, post.id)
    description = truncate_meta(post.excerpt or post.content)
    meta = default_meta(
        title=f"{post.title} — {settings.app_name}",
        description=description or f"Read {post.title} on {settings.app_name}.",
        path=f"/posts/{post.slug}",
        image=post.thumbnail,
        type="article",
        robots="noindex,follow",
    )
    context = page_context(
        request,
        post=post,
        comments=comments,
        captcha_question=captcha_question,
        captcha_token=new_token,
        comment_error=None,
        comment_success=None,
        form_name=name,
        form_email=email,
        form_body=body,
        not_found=False,
        active_nav="articles",
        **meta,
    )

    if not verify_math_captcha(captcha_token, captcha_answer):
        context["comment_error"] = "CAPTCHA-svaret var fel. Försök igen."
        return templates.TemplateResponse(request, "post.html", context, status_code=400)

    if not name.strip() or not email.strip() or not body.strip():
        context["comment_error"] = "Namn, e-post och kommentar krävs."
        return templates.TemplateResponse(request, "post.html", context, status_code=400)

    if not _looks_like_email(email):
        context["comment_error"] = "Ange en giltig e-postadress."
        return templates.TemplateResponse(request, "post.html", context, status_code=400)

    CommentService.create(
        db,
        post_id=post.id,
        name=name,
        email=email,
        body=body,
    )
    return RedirectResponse(
        url=f"/posts/{slug}?commented=1#comments",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/login")
@app.get("/register")
def auth_pages_redirect() -> RedirectResponse:
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/write")
def write_redirect() -> RedirectResponse:
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/robots.txt", response_class=Response)
def robots_txt() -> Response:
    base = settings.site_url.rstrip("/")
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        "Disallow: /write\n"
        "Disallow: /search\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return Response(content=body, media_type="text/plain")


@app.get("/sitemap", response_class=HTMLResponse)
def sitemap_page(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    posts, _ = PostService.list_posts(db, skip=0, limit=1000, published_only=True)
    pages = [
        {"path": "/", "label": "Home"},
        {"path": "/about", "label": "About"},
        {"path": "/ai", "label": "AI"},
        {"path": "/technology", "label": "Technology"},
        {"path": "/analys", "label": "Analys"},
        {"path": "/contact", "label": "Contact"},
        {"path": "/privacy", "label": "Privacy Policy"},
    ]
    meta = default_meta(
        title=f"Sitemap — {settings.app_name}",
        description=f"Browse all public pages and articles on {settings.app_name}.",
        path="/sitemap",
    )
    return templates.TemplateResponse(
        request,
        "sitemap.html",
        page_context(
            request,
            active_nav=None,
            pages=pages,
            posts=posts,
            **meta,
        ),
    )


@app.get("/sitemap.xml", response_class=Response)
def sitemap(db: Session = Depends(get_db)) -> Response:
    base = settings.site_url.rstrip("/")
    static_paths = [
        ("/", "1.0", "daily"),
        ("/about", "0.6", "monthly"),
        ("/ai", "0.8", "weekly"),
        ("/technology", "0.8", "weekly"),
        ("/analys", "0.8", "weekly"),
        ("/contact", "0.5", "monthly"),
        ("/privacy", "0.3", "yearly"),
        ("/sitemap", "0.3", "weekly"),
    ]

    urls: list[str] = []
    for path, priority, changefreq in static_paths:
        urls.append(
            "  <url>\n"
            f"    <loc>{base}{path}</loc>\n"
            f"    <changefreq>{changefreq}</changefreq>\n"
            f"    <priority>{priority}</priority>\n"
            "  </url>"
        )

    posts, _ = PostService.list_posts(db, skip=0, limit=1000, published_only=True)
    for post in posts:
        candidates = [post.updated_at, post.published_at, post.created_at]
        last = max(dt for dt in candidates if dt is not None)
        lastmod = last.date().isoformat()
        urls.append(
            "  <url>\n"
            f"    <loc>{base}/posts/{post.slug}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            "    <changefreq>weekly</changefreq>\n"
            "    <priority>0.7</priority>\n"
            "  </url>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
