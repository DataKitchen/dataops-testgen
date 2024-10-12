import logging

from testgen.common import get_tg_db, get_tg_host, get_tg_password, get_tg_schema, get_tg_username

LOG = logging.getLogger("testgen")


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
