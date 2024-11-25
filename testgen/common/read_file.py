__all__ = ["get_template_files", "read_template_sql_file", "read_template_yaml_file"]

import logging
import re
from collections.abc import Generator
from functools import cache
from importlib.abc import Traversable
from importlib.resources import as_file, files

import yaml

LOG = logging.getLogger("testgen")

DK_FUNCTIONS_PATTERN = re.compile(r"<%(\w+)(?:;(.+?))?%>")
DK_FUNCTIONS_ARG_REPL_PATTERN = re.compile(r"\{\$(\d+)\}")

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


@cache
def read_template_yaml_function(function_name: str, db_flavour: str) -> str:
    yaml_functions = read_template_yaml_file(
        "templated_functions.yaml",
        sub_directory=f"flavors/{db_flavour}/profiling",
    )
    template = yaml_functions[function_name]
    template = re.sub(r"/\*.*?\*/", "", template, flags=re.DOTALL)
    template = re.sub(r"\s\s*", " ", template)
    return template


def replace_templated_functions(query: str, db_flavour: str) -> str:

    # Arguments in the template yaml take the form {$<index>} like {$1}
    # Function template replacement is the last step of templating, therefore cannot use other templated parameters inside.
    # If needed, those must be arguments to the templated function.
    # I.E OK TO DO sql: "<%FOO;{COLUM_NAME}%>" and yaml: "FOO: foo({$1})"
    # NOT OK TO DO sql: "<%FOO%>" and yaml: "FOO: foo({"COLUM_NAME"})"

    query_parts = []
    end_pos = 0
    for func_match in DK_FUNCTIONS_PATTERN.finditer(query):

        query_parts.append(query[end_pos:func_match.span(0)[0]])
        end_pos = func_match.span(0)[1]

        function_name, args_str = func_match.groups()
        function_template = read_template_yaml_function(function_name, db_flavour)
        args = args_str.split(";")

        tpl_end_pos = 0
        for arg_match in DK_FUNCTIONS_ARG_REPL_PATTERN.finditer(function_template):
            query_parts.append(function_template[tpl_end_pos:arg_match.span(0)[0]])
            tpl_end_pos = arg_match.span(0)[1]
            try:
                query_parts.append(args[int(arg_match.group(1)) - 1])
            except IndexError:
                raise ValueError(
                    f"Templated function call missing required arguments: {query[slice(*func_match.span(0))]}"
                ) from None
        query_parts.append(function_template[tpl_end_pos:])

    query_parts.append(query[end_pos:])
    return "".join(query_parts)
