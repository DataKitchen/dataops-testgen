import dataclasses


@dataclasses.dataclass
class ColumnChars:
    schema_name: str
    table_name: str
    column_name: str
    ordinal_position: int | None = None
    general_type: str | None = None
    column_type: str | None = None
    db_data_type: str | None = None
    is_decimal: bool = False
    approx_record_ct: int | None = None
    # This should not default to 0 since we don't always retrieve actual row counts
    # UI relies on the null value to know that the approx_record_ct should be displayed instead
    record_ct: int | None = None
