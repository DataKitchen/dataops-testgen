import logging
from dataclasses import dataclass

import requests

from testgen import settings
from testgen.ui.session import session

LOG = logging.getLogger("testgen")


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
        return {
            "pypi": _get_last_pypi_release,
            "docker": _get_last_docker_release,
            "yes": _get_last_docker_release,  # NOTE: kept for retrocompatibility
        }.get(settings.CHECK_FOR_LATEST_VERSION, lambda: None)()
    except:
        return None


def _get_last_pypi_release() -> str | None:
    response = requests.get("https://pypi.org/pypi/dataops-testgen/json", timeout=3)
    if response.status_code != 200:
        LOG.warning(f"version_service: Failed to fetch PyPi releases. Status code: {response.status_code}")
        return None

    package_data = response.json()
    package_releases = list((package_data.get("releases") or {}).keys())

    return _sorted_tags(package_releases)[0]


def _get_last_docker_release() -> str | None:
    headers = {}
    if settings.DOCKER_HUB_USERNAME and settings.DOCKER_HUB_PASSWORD:
        auth_response = requests.post(
            "https://hub.docker.com/v2/users/login",
            json={"username": settings.DOCKER_HUB_USERNAME, "password": settings.DOCKER_HUB_PASSWORD},
            timeout=5,
        )
        if auth_response.status_code != 200:
            LOG.warning(
                "version_service: unable to login against https://hub.docker.com."
                f" Status code: {auth_response.status_code}"
            )
            return None
        headers["Authorization"] = f"Bearer {auth_response.json()['token']}"

    response = requests.get(
        f"https://hub.docker.com/v2/repositories/{settings.DOCKER_HUB_REPOSITORY}/tags",
        headers=headers,
        params={"page_size": 25, "page": 1, "ordering": "last_updated"},
        timeout=3,
    )

    if response.status_code != 200:
        LOG.debug(f"version_service: Failed to fetch docker tags. Status code: {response.status_code}")
        return None

    tags_to_return = []
    tags_data = response.json()
    results = tags_data.get("results", [])
    for result in results:
        tag_name = result["name"]
        if tag_name.count(".") >= 2 and "experimental" not in tag_name:
            tags_to_return.append(tag_name)

    if len(tags_to_return) <= 0:
        return None

    return _sorted_tags(tags_to_return)[0]


def _sorted_tags(tags: list[str]) -> list[str]:
    sorted_tags_as_tuples = sorted(
        [tuple([ int(i) for i in tag.replace("v", "").split(".") ]) for tag in tags],
        reverse=True,
    )
    return [".".join([str(i) for i in tag_tuple]) for tag_tuple in sorted_tags_as_tuples]
