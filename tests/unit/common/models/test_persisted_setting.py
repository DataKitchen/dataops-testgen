from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.settings import PersistedSetting

pytestmark = pytest.mark.unit


def test_set_returns_the_value_the_upsert_replaced():
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = "before"

    with patch("testgen.common.models.settings.get_current_session", return_value=session):
        replaced = PersistedSetting.set("SOME_KEY", "after")

    compiled = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).split())
    # A subquery in RETURNING reads the snapshot taken before the statement, so it sees the replaced row
    assert "ON CONFLICT (key) DO UPDATE SET value = excluded.value" in sql
    assert sql.endswith("RETURNING (SELECT settings.value FROM settings WHERE settings.key = %(key_1)s) AS anon_1")
    assert compiled.params["key_1"] == "SOME_KEY"
    assert replaced == "before"
