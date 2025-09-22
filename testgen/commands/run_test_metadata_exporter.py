import logging

from testgen import settings
from testgen.common.credentials import get_tg_schema
from testgen.common.models import with_database_session
from testgen.common.read_yaml_metadata_records import export_metadata_records_to_yaml

LOG = logging.getLogger("testgen")

def _get_params_mapping() -> dict:
    return {
        "SCHEMA_NAME": get_tg_schema(),
        "TESTGEN_ADMIN_USER": settings.DATABASE_ADMIN_USER,
        "TESTGEN_ADMIN_PASSWORD": settings.DATABASE_ADMIN_PASSWORD,
    }

@with_database_session
def run_test_metadata_exporter(templates_path) -> None:
    export_metadata_records_to_yaml(_get_params_mapping(), templates_path)
