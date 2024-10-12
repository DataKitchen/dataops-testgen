import csv
import os

import click
from prettytable import PrettyTable


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
    click.echo(f"Output written to: ~/testgen/file-out/{file_name}")


def get_in_out_paths():
    # create the paths if not exist
    home = os.path.expanduser("~")
    file_in_path = os.path.join(home, "testgen", "file-in")
    file_out_path = os.path.join(home, "testgen", "file-out")
    os.makedirs(file_in_path, exist_ok=True)
    os.makedirs(file_out_path, exist_ok=True)
    return file_in_path, file_out_path
