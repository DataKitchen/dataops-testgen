__all__ = ["get_template_files", "read_template_sql_file", "read_template_yaml_file"]

import logging
import re
from collections.abc import Generator
from functools import cache
from importlib.abc import Traversable
from importlib.resources import as_file, files

import yaml

LOG = logging.getLogger("testgen")


def _get_template_package_resource(
    template_file_name: str | None = None,
    sub_directory: str | None = None,
    path: str | None = None,
) -> Traversable:
    if path is None:
        path = "testgen.template"
    if sub_directory:
        path = f"{path}.{sub_directory.replace('/', '.')}"
    if template_file_name:
        return files(path).joinpath(template_file_name)
    else:
        return files(path)


@cache
def read_template_sql_file(template_file_name: str, sub_directory: str | None = None) -> str:
    file = _get_template_package_resource(template_file_name, sub_directory)
    LOG.debug("Reading SQL resource: %s", str(file))
    try:
        contents = file.read_text(encoding="utf-8").strip()
    except FileNotFoundError as e:
        raise ValueError(f"template.{sub_directory}.{template_file_name}: File not found") from e

    if not contents.strip():
        raise ValueError(f"template.{sub_directory}.{template_file_name}: file is empty")

    return contents


def get_template_files(mask: str, sub_directory: str | None = None, path: str | None = None) -> Generator[Traversable, None, None]:
    folder = _get_template_package_resource(template_file_name=None, sub_directory=sub_directory, path=path)
    LOG.debug("Reading SQL folder resource: %s", str(folder))
    for entry in folder.iterdir():
        if entry.is_file() and re.search(mask, str(entry)):
            yield entry


@cache
def read_template_yaml_file(template_file_name: str, sub_directory: str | None = None) -> dict:
    if not template_file_name.endswith(("yaml", "yml")):
        raise ValueError(f"{template_file_name}: does not have a yaml/yml suffix; is it yaml?")
    resource_file = _get_template_package_resource(template_file_name=template_file_name, sub_directory=sub_directory)
    LOG.debug("Reading Yaml resource: %s", str(resource_file))

    try:
        with as_file(resource_file) as f:
            with f.open("r") as file:
                template = yaml.safe_load(file)
    except FileNotFoundError as e:
        raise ValueError(f"{template_file_name}: File not found") from e
    if not template:
        raise ValueError(f"{template_file_name}: File is empty")

    return template
