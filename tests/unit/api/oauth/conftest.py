"""Shared fixtures for OAuth tests."""

import os

# authlib rejects http:// URIs by default; allow in tests
os.environ.setdefault("AUTHLIB_INSECURE_TRANSPORT", "1")
