__all__ = ["CleanSQL", "AddQuotesToIdentifierCSV"]

import re


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


def AddQuotesToIdentifierCSV(strInput: str) -> str:
    # Keywords -- identifiers to quote
    keywords = [
        "select",
        "from",
        "where",
        "order",
        "by",
        "having",
    ]

    quoted_values = []
    for value in strInput.split(","):
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            quoted_values.append(value)
        elif any(c.isupper() or c.isspace() or value.lower() in keywords for c in value):
            quoted_values.append(f'"{value}"')
        else:
            quoted_values.append(value)
    return ", ".join(quoted_values)
