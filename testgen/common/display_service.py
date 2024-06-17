import csv
import logging
import os

import click
import yaml
from prettytable import PrettyTable

LOG = logging.getLogger("testgen")


def print_table(rows: list[dict], column_names: list[str]):
    table = PrettyTable(column_names)
    table.max_width = 80
    table.align = "l"

    for row in rows:
        table.add_row(row)
    click.echo(table)


def to_csv(file_name: str, rows: list[dict], column_names: list[str]):
    _, file_out_path = get_in_out_paths()
    full_path = os.path.join(file_out_path, file_name)
    with open(full_path, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(column_names)
        for row in rows:
            writer.writerow(row)
    echo(f"Output written to: ~/testgen/file-out/{file_name}")


def get_in_out_paths():
    # create the paths if not exist
    home = os.path.expanduser("~")
    file_in_path = os.path.join(home, "testgen", "file-in")
    file_out_path = os.path.join(home, "testgen", "file-out")
    os.makedirs(file_in_path, exist_ok=True)
    os.makedirs(file_out_path, exist_ok=True)
    return file_in_path, file_out_path


def write_to_file(full_path_and_name: str, file_content: str):
    with open(full_path_and_name, "w") as file:
        file.write(file_content)


def to_yaml(file_name: str, yaml_dict: dict, display: bool):
    yaml_content = yaml.dump(yaml_dict, sort_keys=False)
    yaml_content.replace("None", "null")

    _, file_out_path = get_in_out_paths()
    full_path = os.path.join(file_out_path, file_name)
    with open(full_path, "w", newline="") as file:
        file.write(yaml_content)

    if display:
        echo(yaml_content + "\n")

    echo(f"Output written to: ~/testgen/file-out/{file_name}")


def echo(message: str):
    click.echo(message)


def from_yaml(file_name: str, display: bool):
    echo(f"Attempting to read from : ~/testgen/file-in/{file_name}")
    file_in_path, _ = get_in_out_paths()
    full_path = os.path.join(file_in_path, file_name)
    with open(full_path, newline="") as file:
        yaml_content = yaml.safe_load(file)

    if display:
        data = yaml.dump(yaml_content, sort_keys=False)
        echo(data)

    return yaml_content


def check_config_file_presence(file_name: str) -> None:
    file_in_path, _ = get_in_out_paths()
    full_path = os.path.join(file_in_path, file_name)
    if not os.path.exists(full_path):
        echo(click.style(f"Warning: File ~/testgen/file-in/{file_name} is not present.", fg="yellow"))
