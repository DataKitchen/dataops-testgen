def object_name(label: str | None, table_name: str | None, column_name: str | None = None) -> str | None:
    """The name an audit record gives an object that has none of its own: its kind and what it is on.

    ``Alpha Truncation on orders.amount``, ``Row Count on orders``, or the kind alone when it names no table.
    """
    if not table_name:
        return label
    on = f"{table_name}.{column_name}" if column_name else table_name
    return f"{label} on {on}" if label else on
