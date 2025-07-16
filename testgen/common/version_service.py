import logging
from dataclasses import dataclass

import requests

from testgen import settings
from testgen.ui.session import session

LOG = logging.getLogger("testgen")
LATEST_VERSIONS_URL = "https://dk-support-external.s3.us-east-1.amazonaws.com/testgen-observability/testgen-latest-versions.json"


@dataclass
class Version:
    edition: str
    current: str
    latest: str


def get_version() -> Version:
    if not session.version:
        session.version = Version(
            edition=_get_app_edition(),
            current=settings.VERSION,
            latest=_get_latest_version(),
        )
    return session.version


def _get_app_edition() -> str:
    edition = (
        settings.DOCKER_HUB_REPOSITORY
        .replace("datakitchen/dataops-testgen", "")
        .replace("-", " ")
        .strip()
        .title()
        .replace("Qa", "QA")        
    )
    return f"TestGen{' ' + edition if edition else ''}"


def _get_latest_version() -> str | None:
    try:
        response = requests.get(LATEST_VERSIONS_URL, timeout=3)
        if response.status_code != 200:
            LOG.warning(f"Failed to fetch latest versions from S3. Status code: {response.status_code}")
            return None
        
        latest_versions = response.json()

        if settings.CHECK_FOR_LATEST_VERSION == "pypi":
            return latest_versions.get("pypi")

        return latest_versions.get("docker", {}).get(settings.DOCKER_HUB_REPOSITORY)
    except:
        return None
