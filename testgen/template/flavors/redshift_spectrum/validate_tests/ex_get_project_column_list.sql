select concat(concat(concat(schemaname, '.'), concat(tablename, '.')), columnname) as columns
from svv_external_columns
where schemaname in ({TEST_SCHEMAS});
