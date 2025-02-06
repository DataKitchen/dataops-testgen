import platform
import urllib.parse

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from testgen import settings

engine = create_engine(
    url=(
        f"postgresql://{settings.DATABASE_USER}:{urllib.parse.quote_plus(str(settings.DATABASE_PASSWORD))}"
        f"@{settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{settings.DATABASE_NAME}"
    ),
    echo=False,
    connect_args={
        "application_name": platform.node(),
        "options": f"-csearch_path={settings.DATABASE_SCHEMA}",
    },
)

Base = declarative_base()
Session = sessionmaker(
    engine,
    expire_on_commit=False,
)
