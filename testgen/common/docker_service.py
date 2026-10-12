import logging

from testgen.common import get_tg_db, get_tg_host, get_tg_password, get_tg_schema, get_tg_username

LOG = logging.getLogger("testgen")


def check_basic_configuration():
    ret = True
    message = ""

    configs = [
        ("TG_METADATA_DB_HOST", get_tg_host),
        ("TG_METADATA_DB_USER", get_tg_username),
        ("TG_METADATA_DB_PASSWORD", get_tg_password),
        ("TG_METADATA_DB_SCHEMA", get_tg_schema),
        ("TG_METADATA_DB_NAME", get_tg_db),
    ]

    for config in configs:
        if not config[1]():
            ret = False
            message += f"\n{config[0]} is not set."

    if message:
        message = "The system is not properly configured. Please check. Details: \n" + message

    return ret, message
