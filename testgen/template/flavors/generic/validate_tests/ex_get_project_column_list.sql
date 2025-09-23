select concat(concat(concat(table_schema, '.'), concat(table_name, '.')), column_name) as columns
from {COLUMNS_TABLE}
where table_schema in ({TEST_SCHEMAS});
