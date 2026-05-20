SET SEARCH_PATH TO {SCHEMA_NAME};

-- Widen project_user to accommodate Salesforce Data 360 Consumer Keys (86+ chars)
ALTER TABLE connections ALTER COLUMN project_user TYPE VARCHAR(256);
