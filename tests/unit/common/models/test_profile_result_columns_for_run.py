from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from testgen.common.models.profile_result import ColumnSort, ProfileResult


@patch.object(ProfileResult, "_paginate", return_value=([], 0))
def test_a_column_without_its_own_critical_data_element_flag_takes_its_tables(paginate_mock):
    ProfileResult.list_columns_for_run(uuid4(), sort=ColumnSort.table, page=1, limit=10)

    compiled = paginate_mock.call_args.args[0].compile(dialect=postgresql.dialect())
    assert (
        "coalesce(data_column_chars.critical_data_element, data_table_chars.critical_data_element, "
        "%(coalesce_1)s) AS critical_data_element"
    ) in str(compiled)
    assert compiled.params["coalesce_1"] is False
