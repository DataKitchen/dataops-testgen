SELECT id,
       project_code as project_key,
       project_name,
       observability_api_key
FROM projects
ORDER BY effective_from_date desc;
