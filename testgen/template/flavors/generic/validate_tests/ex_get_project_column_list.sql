select concat(concat(concat(table_schema, '.'), concat(table_name, '.')), column_name) as columns
from information_schema.columns
where table_schema in ({TEST_SCHEMAS});
