import pytest

from testgen import settings


@pytest.mark.unit
@pytest.mark.parametrize(
    ("sslmode", "sslrootcert", "expected"),
    [
        (None, "system", {}),
        (None, "/dk/certs/ca.pem", {}),
        ("verify-full", "system", {"sslmode": "verify-full", "sslrootcert": "system"}),
        ("verify-full", "/dk/certs/ca.pem", {"sslmode": "verify-full", "sslrootcert": "/dk/certs/ca.pem"}),
        ("verify-ca", "/dk/certs/ca.pem", {"sslmode": "verify-ca", "sslrootcert": "/dk/certs/ca.pem"}),
        ("require", "/dk/certs/ca.pem", {"sslmode": "require", "sslrootcert": "/dk/certs/ca.pem"}),
        ("prefer", "/dk/certs/ca.pem", {"sslmode": "prefer", "sslrootcert": "/dk/certs/ca.pem"}),
        # libpq rejects sslrootcert=system alongside anything weaker than verify-full.
        ("verify-ca", "system", {"sslmode": "verify-ca"}),
        ("require", "system", {"sslmode": "require"}),
        ("disable", "system", {"sslmode": "disable"}),
    ],
)
def test_database_ssl_connect_args(monkeypatch, sslmode, sslrootcert, expected):
    monkeypatch.setattr(settings, "DATABASE_SSLMODE", sslmode)
    monkeypatch.setattr(settings, "DATABASE_SSLROOTCERT", sslrootcert)

    assert settings._database_ssl_connect_args() == expected
