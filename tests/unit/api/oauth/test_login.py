"""Tests for testgen.api.oauth.login — HTML login page renderer."""

from testgen.api.oauth.login import render_login_page


def _render(**kwargs):
    defaults = {
        "client_id": "test_client",
        "redirect_uri": "http://localhost/callback",
        "response_type": "code",
        "scope": "",
        "state": "xyz",
        "code_challenge": "abc",
        "code_challenge_method": "S256",
    }
    defaults.update(kwargs)
    return render_login_page(**defaults)


def test_login_page_contains_form():
    html = _render()
    assert '<form method="POST"' in html
    assert 'action="/oauth/authorize"' in html


def test_login_page_contains_hidden_fields():
    html = _render(client_id="my_client", state="mystate")
    assert 'name="client_id" value="my_client"' in html
    assert 'name="state" value="mystate"' in html


def test_login_page_shows_error():
    html = _render(error="Bad credentials")
    assert "Bad credentials" in html
    assert "error" in html


def test_login_page_no_error_by_default():
    html = _render()
    assert "error" not in html.split("<form")[0] or 'class="error"' not in html


def test_login_page_shows_client_name():
    html = _render(client_name="Claude Desktop")
    assert "Claude Desktop" in html


def test_login_page_falls_back_to_client_id():
    html = _render(client_id="abc123", client_name="")
    assert "abc123" in html


def test_login_page_escapes_html():
    html = _render(client_name="<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_login_page_has_dark_mode_support():
    html = _render()
    assert "prefers-color-scheme: dark" in html


def test_login_page_has_username_and_password_inputs():
    html = _render()
    assert 'name="username"' in html
    assert 'name="password"' in html
    assert 'type="password"' in html
