"""A target engine's pool holds as many connections as a run can ask for at once."""

import pytest

from testgen.common.database.database_service import get_flavor_service
from testgen.common.database.flavor.salesforce_data360_flavor_service import SalesforceData360FlavorService
from testgen.common.flavors import MAX_THREADS_MAX

pytestmark = pytest.mark.unit

POSTGRES_PARAMS = {
    "sql_flavor": "postgresql",
    "project_host": "localhost",
    "project_port": "5432",
    "project_user": "tg_user",
    "project_pw_encrypted": "secret",
    "project_db": "analytics",
}


def test_a_target_pool_fits_the_largest_thread_count():
    engine = get_flavor_service("postgresql").create_engine(POSTGRES_PARAMS)
    assert engine.pool.size() + engine.pool._max_overflow >= MAX_THREADS_MAX


def test_a_flavor_that_picks_its_own_pool_keeps_it():
    params = {
        "sql_flavor": "salesforce_data360",
        "project_host": "https://myorg.my.salesforce.com",
        "project_user": "consumer_key",
        "project_pw_encrypted": "consumer_secret",
    }
    engine = SalesforceData360FlavorService().create_engine(params)
    assert type(engine.pool).__name__ == "StaticPool"
