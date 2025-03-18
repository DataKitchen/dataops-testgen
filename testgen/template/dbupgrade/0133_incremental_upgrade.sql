SET SEARCH_PATH TO {SCHEMA_NAME};

UPDATE auth_users
   SET role = 'data_quality'
 WHERE role = 'edit';

UPDATE auth_users
   SET role = 'analyst'
 WHERE role = 'read';
