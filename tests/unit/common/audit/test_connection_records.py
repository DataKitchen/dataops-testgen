import pytest
from sqlalchemy.orm import make_transient_to_detached

from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import record
from testgen.common.models.connection import Connection

pytestmark = pytest.mark.unit


def test_a_credentials_change_is_recorded_like_any_other_field_without_its_value_and_the_type_with_it(audit_session, audit_log):
    connection = Connection(
        connection_id=7, project_code="demo", connection_name="Warehouse", sql_flavor="postgresql",
        project_host="db-1", project_user="loader", project_pw_encrypted="old-password", sql_flavor_code="postgresql",
    )
    make_transient_to_detached(connection)
    connection.project_host = "db-2"
    connection.project_pw_encrypted = "new-password"
    connection.sql_flavor_code = "redshift"

    record(AuditAction.CONNECTION_UPDATED, connection)
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["target_type"], entry["targets"], entry["target_name"], entry["project_code"]) == (
        "connection", ["7"], "Warehouse", "demo",
    )
    assert entry["changes"] == {
        "project_host": {"from": "db-1", "to": "db-2"},
        "project_pw_encrypted": {},
        "sql_flavor_code": {"from": "postgresql", "to": "redshift"},
    }
    assert "password" not in str(entry).replace("project_pw_encrypted", "")
