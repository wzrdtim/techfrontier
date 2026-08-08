import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["DEBUG"] = "true"
os.environ["ADMIN_EMAIL"] = "admin@example.com"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin"

from app.core.config import get_settings
from app.core import database as db_module
from app.core.database import Base, get_db
from app.main import app

get_settings.cache_clear()
settings = get_settings()
AUTH_COOKIE = settings.auth_cookie_name
CSRF_COOKIE = settings.csrf_cookie_name


def _captcha_answer_pair():
    from app.core.captcha import create_math_captcha_with_answer

    _question, token, answer = create_math_captcha_with_answer()
    return token, answer


def _admin_login(client):
    client.get("/admin/login")
    csrf = client.cookies.get(CSRF_COOKIE)
    return client.post(
        "/admin/login",
        data={"username": "admin", "password": "admin", "csrf_token": csrf},
        follow_redirects=False,
    )


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_module.engine = engine
db_module.SessionLocal = TestingSessionLocal


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        from app.services.auth_service import AuthService
        from app.services.tag_service import TagService

        AuthService.ensure_admin_user(db)
        TagService.ensure_default_tags(db)
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_admin_api_login_and_create_post(client):
    register = client.post(
        "/api/auth/register",
        json={
            "email": "writer@example.com",
            "username": "writer",
            "password": "password123",
        },
    )
    assert register.status_code == 404

    denied = client.post(
        "/api/posts",
        json={
            "title": "Hello Techfrontier",
            "content": "First post on the blog.\n\nSecond paragraph.",
            "excerpt": "A short intro.",
            "status": "published",
        },
    )
    assert denied.status_code == 401

    login = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert client.cookies.get(AUTH_COOKIE)

    create = client.post(
        "/api/posts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "Hello Techfrontier",
            "content": "First post on the blog.\n\nSecond paragraph.",
            "excerpt": "A short intro.",
            "status": "published",
        },
    )
    assert create.status_code == 201
    body = create.json()
    assert body["slug"] == "hello-techfrontier"
    assert body["author"]["username"] == "admin"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"
    assert me.json()["is_admin"] is True

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert client.cookies.get(AUTH_COOKIE) in (None, "")
    assert client.get("/api/auth/me").status_code == 401

    listing = client.get("/api/posts")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    detail = client.get("/api/posts/hello-techfrontier")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Hello Techfrontier"

    home = client.get("/")
    assert home.status_code == 200
    assert "Hello Techfrontier" in home.text

    public_login = client.get("/login", follow_redirects=False)
    assert public_login.status_code == 303
    assert public_login.headers["location"] == "/admin/login"
    public_register = client.get("/register", follow_redirects=False)
    assert public_register.status_code == 303
    assert public_register.headers["location"] == "/admin/login"


def test_login_rejects_bad_password(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_api_login_rejects_non_admin(client):
    from app.models.user import User
    from app.services.auth_service import AuthService

    db = TestingSessionLocal()
    try:
        db.add(
            User(
                email="writer@example.com",
                username="writer",
                hashed_password=AuthService.hash_password("password123"),
                is_admin=False,
                is_active=True,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/auth/login",
        json={"email": "writer@example.com", "password": "password123"},
    )
    assert response.status_code == 403


def test_admin_crud_flow(client):
    denied = client.get("/admin", follow_redirects=False)
    assert denied.status_code == 303
    assert denied.headers["location"] == "/admin/login"

    login_page = client.get("/admin/login")
    assert login_page.status_code == 200
    csrf = client.cookies.get(CSRF_COOKIE)
    assert csrf

    missing_csrf = client.post(
        "/admin/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert missing_csrf.status_code == 403

    bad = client.post(
        "/admin/login",
        data={"username": "admin", "password": "wrong", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert bad.status_code == 401

    login = client.post(
        "/admin/login",
        data={"username": "admin", "password": "admin", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/admin"

    # Login rotates the CSRF cookie; refresh from jar for later POSTs.
    csrf = client.cookies.get(CSRF_COOKIE)
    assert csrf

    create = client.post(
        "/admin/posts/new",
        data={
            "title": "Admin Post",
            "excerpt": "From the panel",
            "content": "Body text here.",
            "status": "published",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert create.status_code == 303

    dashboard = client.get("/admin")
    assert dashboard.status_code == 200
    assert "Admin Dashboard" in dashboard.text
    assert "Recent articles" in dashboard.text
    assert "Admin Post" in dashboard.text
    csrf = client.cookies.get(CSRF_COOKIE)

    articles = client.get("/admin/articles")
    assert articles.status_code == 200
    assert "Admin Post" in articles.text

    listing = client.get("/api/posts")
    assert listing.json()["total"] == 1
    post_id = listing.json()["items"][0]["id"]
    assert listing.json()["items"][0]["status"] == "published"
    assert listing.json()["items"][0]["published_at"] is not None

    edit = client.post(
        f"/admin/posts/{post_id}/edit",
        data={
            "title": "Updated Admin Post",
            "excerpt": "Updated",
            "content": "Updated body.",
            "status": "published",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert edit.status_code == 303

    detail = client.get("/api/posts/updated-admin-post")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Updated Admin Post"

    delete = client.post(
        f"/admin/posts/{post_id}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert delete.status_code == 303
    assert client.get("/api/posts").json()["total"] == 0


def test_admin_post_rejects_csrf_mismatch(client):
    login_page = client.get("/admin/login")
    assert login_page.status_code == 200
    csrf = client.cookies.get(CSRF_COOKIE)

    login = client.post(
        "/admin/login",
        data={"username": "admin", "password": "admin", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert login.status_code == 303

    forged = client.post(
        "/admin/posts/new",
        data={
            "title": "Forged",
            "content": "Nope",
            "status": "published",
            "csrf_token": "not-the-real-token",
        },
        follow_redirects=False,
    )
    assert forged.status_code == 403
    assert client.get("/api/posts").json()["total"] == 0


def test_draft_and_scheduled_visibility(client):
    login_page = client.get("/admin/login")
    csrf = client.cookies.get(CSRF_COOKIE)
    client.post(
        "/admin/login",
        data={"username": "admin", "password": "admin", "csrf_token": csrf},
        follow_redirects=False,
    )
    csrf = client.cookies.get(CSRF_COOKIE)

    draft = client.post(
        "/admin/posts/new",
        data={
            "title": "Draft Only",
            "content": "Hidden body",
            "status": "draft",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert draft.status_code == 303
    assert client.get("/api/posts").json()["total"] == 0

    future = client.post(
        "/admin/posts/new",
        data={
            "title": "Later Post",
            "content": "Not yet",
            "status": "scheduled",
            "published_at": "2099-01-01T12:00",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert future.status_code == 303
    assert client.get("/api/posts").json()["total"] == 0
    assert client.get("/posts/later-post").status_code == 404

    past = client.post(
        "/admin/posts/new",
        data={
            "title": "Due Scheduled",
            "content": "Should be live",
            "status": "scheduled",
            "published_at": "2020-01-01T12:00",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert past.status_code == 303
    listing = client.get("/api/posts").json()
    assert listing["total"] == 1
    assert listing["items"][0]["status"] == "published"
    assert listing["items"][0]["slug"] == "due-scheduled"


def test_comment_moderation_flow(client):
    _admin_login(client)
    csrf = client.cookies.get(CSRF_COOKIE)

    create = client.post(
        "/admin/posts/new",
        data={
            "title": "Commentable Post",
            "excerpt": "Intro",
            "content": "Body for comments.",
            "status": "published",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert create.status_code == 303
    slug = "commentable-post"

    assert "Inga kommentarer ännu" in client.get(f"/posts/{slug}").text

    captcha_token, answer = _captcha_answer_pair()
    submit = client.post(
        f"/posts/{slug}/comments",
        data={
            "name": "Reader",
            "email": "reader@example.com",
            "body": "Looks great — please approve me.",
            "captcha_token": captcha_token,
            "captcha_answer": answer,
        },
        follow_redirects=False,
    )
    assert submit.status_code == 303
    assert "Looks great" not in client.get(f"/posts/{slug}").text
    assert "väntar på granskning" in client.get(f"/posts/{slug}?commented=1").text

    pending = client.get("/admin/comments")
    assert pending.status_code == 200
    assert "Pending:" in pending.text
    assert "Looks great" in pending.text
    assert "Approve" in pending.text

    import re

    match = re.search(r"/admin/comments/(\d+)/approve", pending.text)
    assert match
    comment_id = match.group(1)
    csrf = client.cookies.get(CSRF_COOKIE)

    approve = client.post(
        f"/admin/comments/{comment_id}/approve?status=pending",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert approve.status_code == 303
    public = client.get(f"/posts/{slug}")
    assert "Looks great" in public.text
    assert "Reader" in public.text

    captcha_token, answer = _captcha_answer_pair()
    client.post(
        f"/posts/{slug}/comments",
        data={
            "name": "Bot",
            "email": "bot@spam.test",
            "body": "Buy cheap widgets now",
            "captcha_token": captcha_token,
            "captcha_answer": answer,
        },
        follow_redirects=False,
    )
    pending = client.get("/admin/comments?status=pending")
    match = re.search(r"/admin/comments/(\d+)/spam", pending.text)
    assert match
    csrf = client.cookies.get(CSRF_COOKIE)
    client.post(
        f"/admin/comments/{match.group(1)}/spam?status=pending",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert "Buy cheap widgets" not in client.get(f"/posts/{slug}").text
    assert "Buy cheap widgets" in client.get("/admin/comments?status=spam").text


def test_contact_form_with_captcha(client):
    page = client.get("/contact")
    assert page.status_code == 200
    assert "Kontakta oss" in page.text
    assert "CAPTCHA" in page.text
    assert 'href="/contact"' in client.get("/").text

    bad = client.post(
        "/contact",
        data={
            "email": "hello@example.com",
            "subject": "Hello",
            "body": "Just saying hi",
            "captcha_token": "invalid",
            "captcha_answer": "1",
        },
    )
    assert bad.status_code == 400
    assert "CAPTCHA" in bad.text

    captcha_token, answer = _captcha_answer_pair()
    ok = client.post(
        "/contact",
        data={
            "email": "hello@example.com",
            "subject": "Hello from a reader",
            "body": "Thanks for the articles.",
            "captcha_token": captcha_token,
            "captcha_answer": answer,
        },
        follow_redirects=False,
    )
    assert ok.status_code == 303
    assert ok.headers["location"] == "/contact?sent=1"
    assert "Ditt meddelande har skickats" in client.get("/contact?sent=1").text

    _admin_login(client)
    inbox = client.get("/admin/messages")
    assert inbox.status_code == 200
    assert "Hello from a reader" in inbox.text
    assert "Thanks for the articles." in inbox.text
