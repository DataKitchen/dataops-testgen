SET SEARCH_PATH TO {SCHEMA_NAME};

-- Value Match and Value Match All store their expected values as a comma-separated list in
-- baseline_value. A value is double-quoted, with " doubled, when it is empty, contains a comma, a
-- double quote or a line break, or has leading or trailing whitespace. A converted list that would not
-- fit baseline_value is left as it was.

-- Value Match All: the quoted, pipe-delimited threshold_value, e.g. 'A|it''s|B', becomes baseline_value,
-- and threshold_value becomes the mismatch count, 0. A threshold without matching outer quotes is
-- copied unchanged.
WITH old_lists AS (
   SELECT id, BTRIM(threshold_value) AS threshold
     FROM test_definitions
    WHERE test_type = 'LOV_All'
      AND COALESCE(baseline_value, '') = ''
      AND COALESCE(BTRIM(threshold_value), '') <> ''
),
converted AS (
   SELECT o.id,
          o.threshold,
          CASE
             WHEN o.threshold ~ '^''.*''$' THEN (
                SELECT STRING_AGG(
                          CASE WHEN val = '' OR val ~ '[,"\r\n]' OR val ~ '^\s|\s$'
                               THEN '"' || REPLACE(val, '"', '""') || '"'
                               ELSE val END,
                          ',' ORDER BY n)
                  -- Unlike STRING_TO_ARRAY, REGEXP_SPLIT_TO_TABLE reads '' as one empty value
                  FROM REGEXP_SPLIT_TO_TABLE(
                          REPLACE(SUBSTRING(o.threshold FROM 2 FOR LENGTH(o.threshold) - 2), '''''', ''''),
                          '\|') WITH ORDINALITY AS v(val, n)
             )
             ELSE o.threshold
          END AS value_list
     FROM old_lists o
)
UPDATE test_definitions td
   SET baseline_value = CASE WHEN LENGTH(c.value_list) <= 1000 THEN c.value_list ELSE c.threshold END,
       threshold_value = '0'
  FROM converted c
 WHERE td.id = c.id;

-- Value Match: the SQL list in baseline_value, ('A','it''s') or (1, 2), becomes comma-separated.
-- Single-quoted items are read with '' as '; unquoted items are split on commas and trimmed. A list
-- in neither form is left unchanged.
WITH old_lists AS (
   SELECT id, BTRIM(SUBSTRING(BTRIM(baseline_value) FROM 2 FOR LENGTH(BTRIM(baseline_value)) - 2)) AS items
     FROM test_definitions
    WHERE test_type = 'LOV_Match'
      AND BTRIM(baseline_value) ~ '^\(.*\)$'
),
list_values AS (
   SELECT o.id, REPLACE(m.item[1], '''''', '''') AS val, m.n
     FROM old_lists o
          CROSS JOIN LATERAL REGEXP_MATCHES(o.items, '''((?:[^'']|'''')*)''', 'g') WITH ORDINALITY AS m(item, n)
    WHERE o.items ~ '^''(?:[^'']|'''')*''(?:\s*,\s*''(?:[^'']|'''')*'')*$'
   UNION ALL
   SELECT o.id, BTRIM(u.val), u.n
     FROM old_lists o
          CROSS JOIN LATERAL UNNEST(STRING_TO_ARRAY(o.items, ',')) WITH ORDINALITY AS u(val, n)
    WHERE o.items ~ '^[^'',]*[^'',\s][^'',]*(?:,[^'',]*[^'',\s][^'',]*)*$'
),
converted AS (
   SELECT id,
          STRING_AGG(
             CASE WHEN val = '' OR val ~ '[,"\r\n]' OR val ~ '^\s|\s$'
                  THEN '"' || REPLACE(val, '"', '""') || '"'
                  ELSE val END,
             ',' ORDER BY n) AS value_list
     FROM list_values
    GROUP BY id
)
UPDATE test_definitions td
   SET baseline_value = c.value_list
  FROM converted c
 WHERE td.id = c.id
   AND LENGTH(c.value_list) <= 1000;
