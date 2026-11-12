import pytest

from testgen.settings import _url_path

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://host/testgen", "testgen"),
        ("https://host/testgen/", "testgen"),
        ("https://host/app/datakitchen-testgen", "app/datakitchen-testgen"),
        ("https://host", ""),
        ("https://host/", ""),
        ("http://localhost:8501", ""),
    ],
)
def test_url_path(url, expected):
    assert _url_path(url) == expected


@pytest.mark.parametrize("url", ["testgen.example.com", "testgen.example.com:8501", ""])
def test_url_path_is_empty_without_a_scheme_and_host(url):
    assert _url_path(url) == ""
