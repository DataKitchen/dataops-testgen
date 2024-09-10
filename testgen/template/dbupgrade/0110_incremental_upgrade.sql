SET SEARCH_PATH TO {SCHEMA_NAME};

WITH duplicates AS (
    SELECT
        id,
        ROW_NUMBER() OVER (PARTITION BY table_groups_name ORDER BY ctid) AS row_num
    FROM
        table_groups
)
UPDATE table_groups tg
SET table_groups_name = tg.table_groups_name || ' ' || to_hex((random() * 10000000)::int)
FROM duplicates d
WHERE tg.id = d.id AND d.row_num > 1;

CREATE UNIQUE INDEX table_groups_name_unique ON table_groups(project_code, table_groups_name);
