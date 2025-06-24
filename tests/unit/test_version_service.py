from unittest import mock

import pytest

from testgen.common.version_service import get_version


@pytest.mark.unit
@mock.patch("testgen.common.version_service.settings")
@mock.patch("testgen.common.version_service.requests")
@mock.patch("testgen.common.version_service.session.version", None)
def test_calls_pypi_api(requests: mock.Mock, settings: mock.Mock):
    settings.CHECK_FOR_LATEST_VERSION = "pypi"
    get_version()
    requests.get.assert_called_with("https://pypi.org/pypi/dataops-testgen/json", timeout=3)


@pytest.mark.unit
@mock.patch("testgen.common.version_service.settings")
@mock.patch("testgen.common.version_service.requests")
@mock.patch("testgen.common.version_service.session.version", None)
def test_return_none_when_pypi_request_fails(requests: mock.Mock, settings: mock.Mock):
    response = mock.Mock()
    response.status_code = 400
    requests.get.return_value = response
    settings.CHECK_FOR_LATEST_VERSION = "pypi"

    assert get_version().latest == None


@pytest.mark.unit
@mock.patch("testgen.common.version_service.settings")
@mock.patch("testgen.common.version_service.requests")
@mock.patch("testgen.common.version_service.session.version", None)
def test_get_the_latest_version_from_pypi(requests: mock.Mock, settings: mock.Mock):
    response = mock.Mock()
    response.status_code = 200
    requests.get.return_value = response
    response.json.return_value = {
        "releases": {
            "0.0.1": "",
            "0.1.0": "",
            "1.0.0": "",
            "1.1.0": "",
            "v1.2.3": "",
            "v1.2.0": "",
        }
    }
    settings.CHECK_FOR_LATEST_VERSION = "pypi"

    assert get_version().latest == "1.2.3"


@pytest.mark.unit
@mock.patch("testgen.common.version_service.settings")
@mock.patch("testgen.common.version_service.requests")
@mock.patch("testgen.common.version_service.session.version", None)
def test_calls_docker_tags_api(requests: mock.Mock, settings: mock.Mock):
    settings.DOCKER_HUB_USERNAME = None
    settings.DOCKER_HUB_PASSWORD = None
    settings.DOCKER_HUB_REPOSITORY = "datakitchen/testgen-a"
    settings.CHECK_FOR_LATEST_VERSION = "docker"
    get_version()

    requests.get.assert_called_with(
        "https://hub.docker.com/v2/repositories/datakitchen/testgen-a/tags",
        headers={},
        params={"page_size": 25, "page": 1, "ordering": "last_updated"},
        timeout=3,
    )


@pytest.mark.unit
@mock.patch("testgen.common.version_service.settings")
@mock.patch("testgen.common.version_service.requests")
@mock.patch("testgen.common.version_service.session.version", None)
def test_return_none_when_docker_request_fails(requests: mock.Mock, settings: mock.Mock):
    response = mock.Mock()
    response.status_code = 400
    requests.get.return_value = response
    settings.DOCKER_HUB_USERNAME = None
    settings.DOCKER_HUB_PASSWORD = None
    settings.CHECK_FOR_LATEST_VERSION = "docker"

    assert get_version().latest == None


@pytest.mark.unit
@mock.patch("testgen.common.version_service.settings")
@mock.patch("testgen.common.version_service.requests")
@mock.patch("testgen.common.version_service.session.version", None)
def test_get_the_latest_version_from_dockerhub(requests: mock.Mock, settings: mock.Mock):
    settings.DOCKER_HUB_USERNAME = None
    settings.DOCKER_HUB_PASSWORD = None
    settings.CHECK_FOR_LATEST_VERSION = "docker"

    response = mock.Mock()
    response.status_code = 200
    requests.get.return_value = response
    response.json.return_value = {
        "results": [
            {"name": "v0.0.1"},
            {"name": "v0.1.0"},
            {"name": "v1.0.0"},
            {"name": "v1.1.0"},
            {"name": "v1.2.0"},
            {"name": "v1.2.3-experimental"},
        ],
    }

    assert get_version().latest == "1.2.0"

@pytest.mark.unit
@mock.patch("testgen.common.version_service.settings")
@mock.patch("testgen.common.version_service.requests")
@mock.patch("testgen.common.version_service.session.version", None)
def test_authenticates_docker_request(requests: mock.Mock, settings: mock.Mock):
    username = settings.DOCKER_HUB_USERNAME = "docker-username"
    password = settings.DOCKER_HUB_PASSWORD = "docker-password"  # noqa: S105
    docker_auth_token = "docker-auth-token"  # noqa: S105
    settings.CHECK_FOR_LATEST_VERSION = "docker"
    settings.DOCKER_HUB_REPOSITORY = "datakitchen/testgen-b"

    response = mock.Mock()
    response.status_code = 200
    response.json.return_value = {"token": docker_auth_token}
    requests.post.return_value = response

    get_version()

    requests.post.assert_called_with(
        "https://hub.docker.com/v2/users/login",
        json={"username": username, "password": password},
        timeout=5,
    )
    requests.get.assert_called_with(
        "https://hub.docker.com/v2/repositories/datakitchen/testgen-b/tags",
        headers={"Authorization": f"Bearer {docker_auth_token}"},
        params={"page_size": 25, "page": 1, "ordering": "last_updated"},
        timeout=3,
    )


@pytest.mark.unit
@mock.patch("testgen.common.version_service.settings")
@mock.patch("testgen.common.version_service.requests")
@mock.patch("testgen.common.version_service.session.version", None)
def test_return_none_when_docker_auth_request_fails(requests: mock.Mock, settings: mock.Mock):
    settings.DOCKER_HUB_USERNAME = "docker-username"
    settings.DOCKER_HUB_PASSWORD = "docker-password"  # noqa: S105
    settings.CHECK_FOR_LATEST_VERSION = "docker"
    settings.DOCKER_HUB_REPOSITORY = "datakitchen/testgen-b"

    response = mock.Mock()
    response.status_code = 400
    requests.post.return_value = response

    assert get_version().latest == None
