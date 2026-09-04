from src.source import canonicalize_url, urls_equivalent, classify_platform, is_social_platform


def test_twitter_x_alias_equivalent():
    assert urls_equivalent(
        "https://twitter.com/user/status/123",
        "https://x.com/user/status/123",
    )


def test_mobile_desktop_variant_equivalent():
    assert urls_equivalent(
        "https://mobile.twitter.com/user/status/123",
        "https://x.com/user/status/123",
    )


def test_tracking_params_stripped():
    a = canonicalize_url("https://x.com/user/status/123?utm_source=fb&fbclid=abc")
    b = canonicalize_url("https://x.com/user/status/123")
    assert a == b


def test_non_tracking_params_preserved():
    a = canonicalize_url("https://example.com/post?id=42")
    b = canonicalize_url("https://example.com/post")
    assert a != b


def test_trailing_slash_normalized():
    a = canonicalize_url("https://x.com/user/status/123/")
    b = canonicalize_url("https://x.com/user/status/123")
    assert a == b


def test_root_path_trailing_slash_preserved():
    assert canonicalize_url("https://example.com/") == canonicalize_url("https://example.com")


def test_fragment_stripped():
    a = canonicalize_url("https://example.com/post#comments")
    b = canonicalize_url("https://example.com/post")
    assert a == b


def test_different_paths_not_equivalent():
    assert not urls_equivalent(
        "https://x.com/user/status/123",
        "https://x.com/user/status/456",
    )


def test_classify_platform():
    assert classify_platform("https://x.com/user/status/1") == "x.com"
    assert classify_platform("https://instagram.com/p/abc") == "instagram.com"
    assert classify_platform("https://unknownsite.example/post") == "unknownsite.example"


def test_classify_platform_rejects_substring_false_positive():
    """'x.com' must not match 'fox.com' just because the characters
    appear inside the hostname -- this was a real fragile-substring bug."""
    assert classify_platform("https://fox.com/article") != "x.com"
    assert classify_platform("https://fox.com/article") == "fox.com"
    assert classify_platform("https://notinstagram.com/page") != "instagram.com"


def test_is_social_platform_true_for_allowlisted_hosts():
    assert is_social_platform("https://x.com/user/status/1") is True
    assert is_social_platform("https://www.instagram.com/p/abc") is True
    assert is_social_platform("https://youtube.com/watch?v=1") is True


def test_is_social_platform_false_for_non_social_hosts():
    assert is_social_platform("https://en.wikipedia.org/wiki/Elon_Musk") is False
    assert is_social_platform("https://www.nytimes.com/article") is False


def test_is_social_platform_rejects_substring_false_positive():
    assert is_social_platform("https://fox.com/article") is False
    assert is_social_platform("https://notinstagram.com/page") is False
