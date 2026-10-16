import json
from importlib import resources

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("filename", ["odcs-json-schema-v3.1.0.json", "odcs-json-schema-v3.2.0.json"])
def test_the_bundled_schema_resolves_as_package_data(filename):
    text = resources.files("testgen.common.odcs.schemas").joinpath(filename).read_text()
    schema = json.loads(text)
    assert schema["$schema"] == "https://json-schema.org/draft/2019-09/schema"


def test_the_bundled_schema_declares_a_v3_2_api_version():
    schema = json.loads(
        resources.files("testgen.common.odcs.schemas")
        .joinpath("odcs-json-schema-v3.2.0.json").read_text()
    )
    assert schema["properties"]["apiVersion"]["default"].startswith("v3.2")
