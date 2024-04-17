from testgen import settings


def get_tg_host() -> str:
    return settings.DATABASE_HOST


def get_tg_port() -> str:
    return settings.DATABASE_PORT


def get_tg_db() -> str:
    return settings.DATABASE_NAME


def get_tg_schema() -> str:
    return settings.DATABASE_SCHEMA


def get_tg_username() -> str:
    return settings.DATABASE_USER


def get_tg_password() -> str:
    return settings.DATABASE_PASSWORD
