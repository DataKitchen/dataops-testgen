import logging

import requests

from testgen import settings
from testgen.common import get_tg_db, get_tg_host, get_tg_password, get_tg_schema, get_tg_username

LOG = logging.getLogger("testgen")



def check_for_new_docker_release() -> str:
    if not settings.CHECK_FOR_LATEST_VERSION:
        return "unknown"

    try:
        tags = get_docker_tags()

        if len(tags) == 0:
            LOG.debug("docker_service: No tags to parse, skipping check.")
            return "unknown"

        ordered_tags = sorted(tags, key=lambda item: item[1], reverse=True)
        latest_tag = ordered_tags[0][0]

        if latest_tag != settings.VERSION:
            LOG.warning(
                f"A new TestGen upgrade is available. Please update to version {latest_tag} for new features and improvements."
            )

        return latest_tag  # noqa: TRY300
    except Exception:
        LOG.warning("Unable to check for latest release", exc_info=True, stack_info=True)


def get_docker_tags(url: str = "https://hub.docker.com/v2/repositories/datakitchen/dataops-testgen/tags/"):
    params = {"page_size": 25, "page": 1, "ordering": "last_updated"}
    response = requests.get(url, params=params, timeout=3)

    tags_to_return = []
    if not response.status_code == 200:
        LOG.warning(f"docker_service: Failed to fetch docker tags. Status code: {response.status_code}")
        return tags_to_return

    tags_data = response.json()
    results = tags_data.get("results", [])
    for result in results:
        tag_name = result["name"]
        last_pushed = result["tag_last_pushed"]
        if tag_name.count(".") >= 2 and "experimental" not in tag_name:
            tags_to_return.append((tag_name, last_pushed))

    return tags_to_return


def check_basic_configuration():
    ret = True
    message = ""

    configs = [
        ("host", get_tg_host),
        ("username", get_tg_username),
        ("password", get_tg_password),
        ("schema", get_tg_schema),
        ("db", get_tg_db),
    ]

    for config in configs:
        if not config[1]():
            ret = False
            message += f"\n{config[0]} configuration is missing."

    if message:
        message = "The system is not properly configured. Please check. Details: \n" + message

    return ret, message
