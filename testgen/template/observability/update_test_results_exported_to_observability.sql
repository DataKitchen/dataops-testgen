/*test-results: customer-code, test-group, result-ids
Output: updates exported results */

with selects
  as ( SELECT UNNEST(ARRAY[{RESULT_IDS}]) AS selected_id )
	update test_results set observability_status = 'Sent'
	from test_results r
	INNER JOIN selects s ON (r.result_id = s.selected_id)
	where r.id = test_results.id
	and r.observability_status = 'Queued'
	and r.test_suite_id = '{TEST_SUITE_ID}'
