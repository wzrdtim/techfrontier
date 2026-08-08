from app.services.analytics_service import (
    AnalyticsService,
    classify_device,
    parse_referrer,
)


def test_classify_device():
    assert classify_device("Mozilla/5.0 (iPhone)") == "mobile"
    assert classify_device("Mozilla/5.0 (Windows NT) Chrome/120") == "desktop"
    assert classify_device("Googlebot/2.1") == "bot"


def test_parse_referrer_sources():
    assert parse_referrer(None, "example.com")[2] == "direct"
    assert parse_referrer("https://www.google.com/search?q=ai", "example.com")[2] == "search"
    assert parse_referrer("https://twitter.com/x", "example.com")[2] == "social"
    assert parse_referrer("https://news.ycombinator.com/", "example.com")[2] == "referral"
    assert parse_referrer("https://example.com/about", "example.com")[2] == "internal"


def test_should_track_skips_admin_and_bots():
    assert AnalyticsService.should_track("GET", "/", 200, "Mozilla/5.0") is True
    assert AnalyticsService.should_track("GET", "/admin", 200, "Mozilla/5.0") is False
    assert AnalyticsService.should_track("GET", "/api/posts", 200, "Mozilla/5.0") is False
    assert AnalyticsService.should_track("POST", "/", 200, "Mozilla/5.0") is False
    assert AnalyticsService.should_track("GET", "/", 200, "Googlebot") is False
