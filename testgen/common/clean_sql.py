import re

from testgen.common.database.database_service import get_flavor_service


def CleanSQL(strInput: str) -> str:
    # Use regular expression to remove comment text fenced by /*...*/
    strInput = re.sub(r"/\*.*?\*/", "", strInput, flags=re.DOTALL)
    # Use regular expression to remove comment text starting with --
    strInput = re.sub(r"--.*$", "", strInput, flags=re.MULTILINE)
    # Use regular expression to replace any tab with one space
    strInput = re.sub(r"\t", " ", strInput)
    # Use regular expression to remove spaces outside quotes
    parts = re.split(r"""("[^"]*"|'[^']*')""", strInput)
    parts[::2] = (" ".join(s.split()) for s in parts[::2])  # outside quotes
    return " ".join(parts)


def quote_identifiers(identifiers: str, flavor: str) -> str:
    if not identifiers:
        return ""

    # Keywords -- identifiers to quote
    keywords = [
        "select",
        "from",
        "where",
        "order",
        "by",
        "having",
    ]
    flavor_service = get_flavor_service(flavor)
    quote = flavor_service.quote_character

    quoted_values = []
    for value in identifiers.split(","):
        value = value.strip()
        if value.startswith(quote) and value.endswith(quote):
            quoted_values.append(value)
        elif any(
            (flavor_service.default_uppercase and c.lower())
            or (not flavor_service.default_uppercase and c.isupper())
            or c.isspace()
            or value.lower() in keywords
            for c in value
        ):
            quoted_values.append(f"{quote}{value}{quote}")
        else:
            quoted_values.append(value)
    return ", ".join(quoted_values)


def concat_columns(columns: str, null_value: str):
    # Prepares SQL expression to concatenate comma-separated column list
    expression = ""
    if columns:
        if "," in columns:
            column_list = [f"COALESCE({col.strip()}, '{null_value}')" for col in columns.split(",")]
            expression = f"CONCAT({', '.join(column_list)})"
        else:
            expression = columns
    return expression
