-- ==============================================================================
-- |   Create default roles and users if not present  |
-- ==============================================================================

-- testgen_execute_role: read-write to operational tables, otherwise read-only
CREATE ROLE testgen_execute_role;

--create user and assign role
CREATE USER {TESTGEN_USER} WITH PASSWORD '{TESTGEN_PASSWORD}';
GRANT testgen_execute_role TO {TESTGEN_USER};

-- testgen_report_role:  Read-Only to all data
CREATE ROLE testgen_report_role;

--create user and assign role
CREATE USER {TESTGEN_REPORT_USER} WITH PASSWORD '{TESTGEN_REPORT_PASSWORD}';
GRANT testgen_report_role TO {TESTGEN_REPORT_USER};
