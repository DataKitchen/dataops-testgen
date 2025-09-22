import logging

from testgen.common.models import with_database_session
from testgen.common.read_yaml_metadata_records import export_metadata_records_to_yaml

LOG = logging.getLogger("testgen")

@with_database_session
def run_test_metadata_exporter(templates_path) -> None:
    export_metadata_records_to_yaml(templates_path)
