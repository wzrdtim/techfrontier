from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.content import sanitize_html
from app.core.csrf import (
    clear_csrf_cookie,
    ensure_csrf_token,
    generate_csrf_token,
    require_csrf,
    set_csrf_cookie,
)
from app.core.cookies import clear_admin_cookie, set_admin_cookie
from app.core.database import get_db
from app.core.images import process_content_image, process_thumbnail_image, read_upload_bytes
from app.core.post_status import POST_STATUS_CHOICES, POST_STATUS_LABELS, PostStatus
from app.core.storage import get_storage, safe_object_key
from app.models.comment import COMMENT_STATUS_LABELS, CommentStatus
from app.models.user import User
from app.schemas.post import PostCreate, PostUpdate
from app.services.analytics_service import AnalyticsService
from app.services.auth_service import AuthService, get_optional_user, require_admin_page
from app.services.comment_service import CommentService
from app.services.contact_service import ContactService
from app.services.newsletter_service import NewsletterService
from app.services.post_service import PostService
from app.services.tag_service import TagService

BASE_DIR = Path(__file__).resolve().parents[3]
ADMIN_TEMPLATES = Jinja2Templates(directory=BASE_DIR / "admin" / "templates")
settings = get_settings()
ADMIN_TEMPLATES.env.globals["thumbnail_max_width"] = settings.thumbnail_max_width
ADMIN_TEMPLATES.env.globals["thumbnail_max_height"] = settings.thumbnail_max_height
ADMIN_TEMPLATES.env.globals["image_max_width"] = settings.image_max_width
ADMIN_TEMPLATES.env.globals["image_max_height"] = settings.image_max_height
ADMIN_TEMPLATES.env.globals["post_statuses"] = [
    {"value": s.value, "label": POST_STATUS_LABELS[s]} for s in POST_STATUS_CHOICES
]
ADMIN_TEMPLATES.env.filters["intcomma"] = lambda value: f"{int(value or 0):,}"

router = APIRouter(prefix="/admin", tags=["admin"])
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}


def _admin_context(request: Request, **extra):
    csrf_token = ensure_csrf_token(request)
    ctx = {
        "request": request,
        "app_name": settings.app_name,
        "csrf_token": csrf_token,
    }
    ctx.update(extra)
    return ctx, csrf_token


def _html(
    request: Request,
    template: str,
    *,
    status_code: int = 200,
    db: Session | None = None,
    **extra,
) -> HTMLResponse:
    if (
        extra.get("admin") is not None
        and "pending_comments" not in extra
        and db is not None
    ):
        extra["pending_comments"] = int(
            CommentService.count_by_status(db, CommentStatus.PENDING)
        )
    if (
        extra.get("admin") is not None
        and "unread_messages" not in extra
        and db is not None
    ):
        extra["unread_messages"] = int(ContactService.count_unread(db))
    context, csrf_token = _admin_context(request, **extra)
    response = ADMIN_TEMPLATES.TemplateResponse(
        request,
        template,
        context,
        status_code=status_code,
    )
    set_csrf_cookie(response, csrf_token)
    return response


def _parse_comment_status(raw: str | None) -> CommentStatus | None:
    if not raw or not str(raw).strip():
        return CommentStatus.PENDING
    value = str(raw).strip().lower()
    if value == "all":
        return None
    try:
        return CommentStatus(value)
    except ValueError:
        return CommentStatus.PENDING


def _comments_redirect(status_filter: str | None) -> RedirectResponse:
    query = f"?status={status_filter}" if status_filter else ""
    return RedirectResponse(
        url=f"/admin/comments{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _parse_tag_ids(raw: Optional[List[str]]) -> list[int]:
    ids: list[int] = []
    for value in raw or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def _parse_status(raw: str | None) -> PostStatus:
    try:
        return PostStatus((raw or PostStatus.DRAFT.value).strip().lower())
    except ValueError:
        return PostStatus.DRAFT


def _parse_published_at(raw: str | None) -> datetime | None:
    if not raw or not str(raw).strip():
        return None
    value = str(raw).strip()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _form_status_context(
    *,
    status_value: PostStatus,
    published_at: datetime | None,
    error: str | None = None,
) -> dict:
    return {
        "form_status": status_value.value,
        "form_published_at": (
            published_at.strftime("%Y-%m-%dT%H:%M") if published_at else ""
        ),
        "error": error,
    }


async def _save_content_upload(file: UploadFile) -> str:
    data = await read_upload_bytes(file)
    return process_content_image(data).url


async def _save_thumbnail_upload(file: UploadFile) -> str:
    data = await read_upload_bytes(file)
    return process_thumbnail_image(data).url


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _list_media_files() -> list[dict]:
    files: list[dict] = []
    for obj in get_storage().list_objects():
        ext = Path(obj.key).suffix.lower()
        files.append(
            {
                "name": obj.key,
                "url": obj.url,
                "ext": ext.lstrip(".").upper() or "FILE",
                "is_image": ext in IMAGE_EXTS,
                "size_label": _format_bytes(obj.size),
                "modified": obj.modified.strftime("%b %d, %Y"),
            }
        )
    return files


@router.get("/login", response_class=HTMLResponse)
def admin_login_page(
    request: Request,
    user: User | None = Depends(get_optional_user),
) -> HTMLResponse:
    if user and user.is_admin:
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    return _html(request, "login.html", error=None)


@router.post("/login", response_class=HTMLResponse)
async def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> HTMLResponse:
    try:
        user = AuthService.authenticate(db, login=username, password=password)
    except Exception:
        return _html(
            request,
            "login.html",
            status_code=status.HTTP_401_UNAUTHORIZED,
            error="Incorrect username or password",
        )

    if not user.is_admin:
        return _html(
            request,
            "login.html",
            status_code=status.HTTP_403_FORBIDDEN,
            error="Admin access required",
        )

    token = AuthService.create_access_token(user.id)
    csrf_token = generate_csrf_token()
    response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    set_admin_cookie(response, token)
    set_csrf_cookie(response, csrf_token)
    return response


@router.post("/logout")
async def admin_logout(
    _: None = Depends(require_csrf),
) -> RedirectResponse:
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_admin_cookie(response)
    clear_csrf_cookie(response)
    return response


@router.post("/uploads")
async def admin_upload(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> JSONResponse:
    saved = process_content_image(await read_upload_bytes(file))
    # TinyMCE expects { location: "..." }
    return JSONResponse(
        {
            "url": saved.url,
            "location": saved.url,
            "width": saved.width,
            "height": saved.height,
            "format": saved.format,
        }
    )


@router.get("", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
) -> HTMLResponse:
    analytics = AnalyticsService.summary(db, days=30)
    return _html(
        request,
        "dashboard.html",
        db=db,
        admin=admin,
        active_nav="dashboard",
        stats={
            "articles": PostService.count_posts(db),
            "views": PostService.total_views(db),
            "subscribers": NewsletterService.count(db),
            "page_views": analytics.page_views,
            "unique_visitors": analytics.unique_visitors,
            "article_views": analytics.article_views,
        },
        analytics=analytics,
        recent_posts=PostService.recent_posts(db, limit=8),
    )


@router.get("/analytics", response_class=HTMLResponse)
def admin_analytics(
    request: Request,
    days: int = 30,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
) -> HTMLResponse:
    window = days if days in {7, 30, 90} else 30
    analytics = AnalyticsService.summary(db, days=window)
    return _html(
        request,
        "analytics.html",
        db=db,
        admin=admin,
        active_nav="analytics",
        analytics=analytics,
        days=window,
    )


@router.get("/articles", response_class=HTMLResponse)
def admin_articles(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
) -> HTMLResponse:
    posts, total = PostService.list_posts(db, skip=0, limit=100, published_only=False)
    return _html(
        request,
        "articles.html",
        db=db,
        admin=admin,
        active_nav="articles",
        posts=posts,
        total=total,
    )


@router.get("/categories", response_class=HTMLResponse)
def admin_categories(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
) -> HTMLResponse:
    return _html(
        request,
        "tags.html",
        db=db,
        admin=admin,
        active_nav="categories",
        page_title="Categories",
        lead="Topic categories used to organize articles on the public site.",
        tags=TagService.list_with_counts(db),
        show_create=False,
        error=None,
    )


@router.get("/tags", response_class=HTMLResponse)
def admin_tags(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
) -> HTMLResponse:
    return _html(
        request,
        "tags.html",
        db=db,
        admin=admin,
        active_nav="tags",
        page_title="Tags",
        lead="Create and manage tags for articles.",
        tags=TagService.list_with_counts(db),
        show_create=True,
        error=None,
    )


@router.post("/tags", response_class=HTMLResponse)
async def admin_create_tag(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> HTMLResponse:
    error = None
    try:
        TagService.create(db, name)
        return RedirectResponse(url="/admin/tags", status_code=status.HTTP_303_SEE_OTHER)
    except ValueError as exc:
        error = str(exc)
    return _html(
        request,
        "tags.html",
        db=db,
        status_code=status.HTTP_400_BAD_REQUEST,
        admin=admin,
        active_nav="tags",
        page_title="Tags",
        lead="Create and manage tags for articles.",
        tags=TagService.list_with_counts(db),
        show_create=True,
        error=error,
    )


@router.post("/tags/{tag_id}/delete")
async def admin_delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> RedirectResponse:
    tag = TagService.get_by_id(db, tag_id)
    if tag is not None:
        TagService.delete(db, tag)
    return RedirectResponse(url="/admin/tags", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/comments", response_class=HTMLResponse)
def admin_comments(
    request: Request,
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
) -> HTMLResponse:
    comment_status = _parse_comment_status(status_filter)
    filter_key = comment_status.value if comment_status else "all"
    comments, total = CommentService.list_recent(
        db,
        status=comment_status,
        limit=100,
    )
    pending = CommentService.count_by_status(db, CommentStatus.PENDING)
    approved = CommentService.count_by_status(db, CommentStatus.APPROVED)
    spam = CommentService.count_by_status(db, CommentStatus.SPAM)
    return _html(
        request,
        "comments.html",
        db=db,
        admin=admin,
        active_nav="comments",
        comments=comments,
        total=total,
        pending_comments=pending,
        status_filter=filter_key,
        status_counts={
            "pending": pending,
            "approved": approved,
            "spam": spam,
            "all": pending + approved + spam,
        },
        status_labels={s.value: label for s, label in COMMENT_STATUS_LABELS.items()},
    )


@router.post("/comments/{comment_id}/approve")
async def admin_approve_comment(
    comment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> RedirectResponse:
    comment = CommentService.get_by_id(db, comment_id)
    if comment is not None:
        CommentService.set_status(db, comment, CommentStatus.APPROVED)
    return _comments_redirect(request.query_params.get("status") or "pending")


@router.post("/comments/{comment_id}/spam")
async def admin_spam_comment(
    comment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> RedirectResponse:
    comment = CommentService.get_by_id(db, comment_id)
    if comment is not None:
        CommentService.set_status(db, comment, CommentStatus.SPAM)
    return _comments_redirect(request.query_params.get("status") or "pending")


@router.post("/comments/{comment_id}/delete")
async def admin_delete_comment(
    comment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> RedirectResponse:
    comment = CommentService.get_by_id(db, comment_id)
    if comment is not None:
        CommentService.delete(db, comment)
    return _comments_redirect(request.query_params.get("status") or "pending")


@router.get("/subscribers", response_class=HTMLResponse)
def admin_subscribers(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
) -> HTMLResponse:
    subscribers, total = NewsletterService.list_subscribers(db, limit=200)
    return _html(
        request,
        "subscribers.html",
        db=db,
        admin=admin,
        active_nav="subscribers",
        subscribers=subscribers,
        total=total,
    )


@router.post("/subscribers/{subscriber_id}/delete")
async def admin_delete_subscriber(
    subscriber_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> RedirectResponse:
    subscriber = NewsletterService.get_by_id(db, subscriber_id)
    if subscriber is not None:
        NewsletterService.delete(db, subscriber)
    return RedirectResponse(
        url="/admin/subscribers", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/messages", response_class=HTMLResponse)
def admin_messages(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
) -> HTMLResponse:
    messages, total = ContactService.list_recent(db, limit=100)
    unread = ContactService.count_unread(db)
    return _html(
        request,
        "messages.html",
        db=db,
        admin=admin,
        active_nav="messages",
        messages=messages,
        total=total,
        unread=unread,
        unread_messages=unread,
    )


@router.post("/messages/{message_id}/read")
async def admin_mark_message_read(
    message_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> RedirectResponse:
    message = ContactService.get_by_id(db, message_id)
    if message is not None:
        ContactService.mark_read(db, message)
    return RedirectResponse(url="/admin/messages", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/messages/{message_id}/delete")
async def admin_delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> RedirectResponse:
    message = ContactService.get_by_id(db, message_id)
    if message is not None:
        ContactService.delete(db, message)
    return RedirectResponse(url="/admin/messages", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/media", response_class=HTMLResponse)
def admin_media(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
) -> HTMLResponse:
    return _html(
        request,
        "media.html",
        db=db,
        admin=admin,
        active_nav="media",
        files=_list_media_files(),
    )


@router.post("/media/delete")
async def admin_delete_media(
    filename: str = Form(...),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> RedirectResponse:
    key = safe_object_key(filename)
    if key:
        storage = get_storage()
        stem = Path(key).stem
        base = stem[: -len("-sm")] if stem.endswith("-sm") else stem
        for sibling in (f"{base}.webp", f"{base}-sm.webp", f"{base}.avif"):
            storage.delete(sibling)
    return RedirectResponse(url="/admin/media", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/settings", response_class=HTMLResponse)
def admin_settings(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
) -> HTMLResponse:
    return _html(
        request,
        "settings.html",
        db=db,
        admin=admin,
        active_nav="settings",
        settings_view={
            "app_name": settings.app_name,
            "site_url": settings.site_url,
            "image_max_width": settings.image_max_width,
            "image_max_height": settings.image_max_height,
        },
    )


@router.get("/posts/new", response_class=HTMLResponse)
def admin_new_post_page(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
) -> HTMLResponse:
    return _html(
        request,
        "post_form.html",
        db=db,
        admin=admin,
        active_nav="articles",
        post=None,
        error=None,
        form_action="/admin/posts/new",
        page_title="New article",
        all_tags=TagService.list_tags(db),
        selected_tag_ids=[],
        form_status=PostStatus.DRAFT.value,
        form_published_at="",
    )


@router.post("/posts/new", response_class=HTMLResponse)
async def admin_create_post(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    excerpt: str = Form(""),
    status_value: str = Form("draft", alias="status"),
    published_at: str | None = Form(None),
    tag_ids: Optional[List[str]] = Form(None),
    thumbnail: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> HTMLResponse:
    title = title.strip()
    content = sanitize_html(content.strip())
    excerpt = excerpt.strip()
    selected = _parse_tag_ids(tag_ids)
    all_tags = TagService.list_tags(db)
    post_status = _parse_status(status_value)
    publish_at = _parse_published_at(published_at)

    def error_page(message: str, code: int = status.HTTP_400_BAD_REQUEST) -> HTMLResponse:
        return _html(
            request,
            "post_form.html",
            status_code=code,
            db=db,
            admin=admin,
            post=None,
            form_action="/admin/posts/new",
            page_title="New article",
            form_title=title,
            form_excerpt=excerpt,
            form_content=content,
            all_tags=all_tags,
            selected_tag_ids=selected,
            active_nav="articles",
            **_form_status_context(
                status_value=post_status,
                published_at=publish_at,
                error=message,
            ),
        )

    if not title or not content:
        return error_page("Title and content are required")

    if post_status == PostStatus.SCHEDULED and publish_at is None:
        return error_page("Scheduled posts need a publish date and time")

    thumbnail_url = None
    if thumbnail is not None and thumbnail.filename:
        thumbnail_url = await _save_thumbnail_upload(thumbnail)

    tags = TagService.get_by_ids(db, selected)
    try:
        PostService.create(
            db,
            PostCreate(
                title=title,
                content=content,
                excerpt=excerpt or None,
                thumbnail=thumbnail_url,
                status=post_status,
                published_at=publish_at,
            ),
            author_id=admin.id,
            tags=tags,
        )
    except ValueError as exc:
        return error_page(str(exc))
    return RedirectResponse(url="/admin/articles", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/posts/{post_id}/edit", response_class=HTMLResponse)
def admin_edit_post_page(
    post_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
) -> HTMLResponse:
    post = PostService.get_by_id(db, post_id)
    if post is None:
        return RedirectResponse(url="/admin/articles", status_code=status.HTTP_303_SEE_OTHER)
    return _html(
        request,
        "post_form.html",
        db=db,
        admin=admin,
        active_nav="articles",
        post=post,
        error=None,
        form_action=f"/admin/posts/{post.id}/edit",
        page_title="Edit article",
        all_tags=TagService.list_tags(db),
        selected_tag_ids=[tag.id for tag in post.tags],
        form_status=post.status,
        form_published_at=(
            post.published_at.strftime("%Y-%m-%dT%H:%M") if post.published_at else ""
        ),
    )


@router.post("/posts/{post_id}/edit", response_class=HTMLResponse)
async def admin_update_post(
    post_id: int,
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    excerpt: str = Form(""),
    status_value: str = Form("draft", alias="status"),
    published_at: str | None = Form(None),
    tag_ids: Optional[List[str]] = Form(None),
    thumbnail: UploadFile | None = File(None),
    remove_thumbnail: str | None = Form(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> HTMLResponse:
    post = PostService.get_by_id(db, post_id)
    if post is None:
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

    title = title.strip()
    content = sanitize_html(content.strip())
    excerpt = excerpt.strip()
    selected = _parse_tag_ids(tag_ids)
    all_tags = TagService.list_tags(db)
    post_status = _parse_status(status_value)
    publish_at = _parse_published_at(published_at)

    def error_page(message: str) -> HTMLResponse:
        return _html(
            request,
            "post_form.html",
            status_code=status.HTTP_400_BAD_REQUEST,
            db=db,
            admin=admin,
            post=post,
            form_action=f"/admin/posts/{post.id}/edit",
            page_title="Edit article",
            form_title=title,
            form_excerpt=excerpt,
            form_content=content,
            all_tags=all_tags,
            selected_tag_ids=selected,
            active_nav="articles",
            **_form_status_context(
                status_value=post_status,
                published_at=publish_at,
                error=message,
            ),
        )

    if not title or not content:
        return error_page("Title and content are required")

    if post_status == PostStatus.SCHEDULED and publish_at is None:
        return error_page("Scheduled posts need a publish date and time")

    update = PostUpdate(
        title=title,
        content=content,
        excerpt=excerpt or None,
        status=post_status,
        published_at=publish_at,
    )
    if remove_thumbnail is not None:
        update.thumbnail = None
    elif thumbnail is not None and thumbnail.filename:
        update.thumbnail = await _save_thumbnail_upload(thumbnail)

    tags = TagService.get_by_ids(db, selected)
    try:
        PostService.update(db, post, update, tags=tags, update_tags=True)
    except ValueError as exc:
        return error_page(str(exc))
    return RedirectResponse(url="/admin/articles", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/posts/{post_id}/delete")
async def admin_delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_page),
    _: None = Depends(require_csrf),
) -> RedirectResponse:
    post = PostService.get_by_id(db, post_id)
    if post is not None:
        PostService.delete(db, post)
    return RedirectResponse(url="/admin/articles", status_code=status.HTTP_303_SEE_OTHER)
