"""The Amazon S3 and Azure Blob Storage codes of the DuckDB flavor.

Nothing here reaches a real store. Registering credentials, confining reads and translating the
stores' failures are all checked against DuckDB itself or against the failure text the stores
return, captured from real requests.
"""

from collections.abc import Callable
from unittest.mock import MagicMock

import duckdb
import pytest

from testgen.common.database.file_declarations import FileDeclaration
from testgen.common.database.flavor import duckdb_flavor_service
from testgen.common.database.flavor import duckdb_object_storage as object_storage
from testgen.common.database.flavor.duckdb_flavor_service import (
    DuckdbConnectionError,
    DuckdbFlavorService,
    base_location,
)
from testgen.common.database.flavor.flavor_service import resolve_connection_params
from testgen.common.enums import FileFormat
from testgen.common.flavors import (
    FLAVOR_CODE_TO_FAMILY,
    FLAVOR_CODE_TO_LABEL,
    FLAVOR_DECLARES_FILES,
    SqlFlavorCode,
    declares_files,
    fixed_max_threads,
    fixed_table_group_schema,
)

pytestmark = pytest.mark.unit

S3_KEYS = {"base_uri": "s3://claims-bucket/monthly", "region": "us-east-1", "strategy": "access_keys", "access_key_id": "AKIAEXAMPLE"}
S3_SECRETS = {"secret_access_key": "s3-secret-value"}
S3_ROLE = {"base_uri": "s3://claims-bucket/monthly", "region": "us-east-1", "strategy": "iam_role"}

AZURE_KEY = {"storage_account": "claimsacct", "container": "claims", "strategy": "account_key"}
AZURE_KEY_SECRETS = {"account_key": "YXp1cmUta2V5LXZhbHVl"}
AZURE_SPN = {
    "storage_account": "claimsacct",
    "container": "claims",
    "strategy": "service_principal",
    "client_id": "client-guid",
    "tenant_id": "tenant-guid",
}
AZURE_SPN_SECRETS = {"client_secret": "spn-secret-value"}
S3_NO_CREDENTIALS = (
    "No credentials were found. The credential chain looks for AWS credentials in the environment running "
    "TestGen. From inside a container, an EC2 instance role requires the instance metadata hop limit to be 2."
)

AZURE_MI = {"storage_account": "claimsacct", "container": "claims", "strategy": "managed_identity"}


def connection_params(code: str, parameters: dict, secrets: dict | None = None) -> dict:
    return {"sql_flavor": "duckdb", "sql_flavor_code": code, "parameters": parameters, "secrets": secrets or {}}


# -- registration -------------------------------------------------------------


@pytest.mark.parametrize(("code", "label"), [(SqlFlavorCode.S3, "Amazon S3"), (SqlFlavorCode.AZURE_BLOB, "Azure Blob Storage")])
def test_each_storage_code_is_a_file_code_of_the_duckdb_family(code, label):
    assert FLAVOR_CODE_TO_FAMILY[code] == "duckdb"
    assert str(FLAVOR_CODE_TO_LABEL[code]) == label
    assert declares_files(code)
    assert fixed_table_group_schema(code) == "main"
    assert fixed_max_threads(code) == 1


def test_every_file_code_but_a_mounted_path_reads_through_a_store():
    """A file code with no store would fall back to reading its declarations from the local disk."""
    assert set(object_storage.STORES) == set(FLAVOR_DECLARES_FILES) - {SqlFlavorCode.FILES}
    assert object_storage.store_for(SqlFlavorCode.FILES) is None
    assert object_storage.store_for(None) is None


# -- base location --------------------------------------------------------------


def test_the_s3_base_location_is_the_base_uri_without_a_trailing_slash():
    assert base_location("s3", {**S3_KEYS, "base_uri": " s3://claims-bucket/monthly/ "}) == "s3://claims-bucket/monthly"


def test_the_azure_base_location_is_the_container():
    assert base_location("azure_blob", AZURE_KEY) == "az://claims"


def test_a_storage_connection_with_no_location_has_no_base_location():
    assert base_location("s3", {}) == ""
    assert base_location("azure_blob", {}) == ""


# -- validation ---------------------------------------------------------------


def validate(code: str, parameters: dict, secrets: dict | None = None) -> None:
    DuckdbFlavorService().validate_settings(parameters, secrets, code)


@pytest.mark.parametrize(
    ("code", "parameters", "secrets"),
    [
        ("s3", S3_KEYS, S3_SECRETS),
        ("s3", S3_ROLE, None),
        ("azure_blob", AZURE_KEY, AZURE_KEY_SECRETS),
        ("azure_blob", AZURE_SPN, AZURE_SPN_SECRETS),
        ("azure_blob", AZURE_MI, None),
    ],
)
def test_every_strategy_validates_with_what_it_needs(code, parameters, secrets):
    validate(code, parameters, secrets)


@pytest.mark.parametrize(
    ("code", "parameters", "secrets", "message"),
    [
        ("s3", {**S3_KEYS, "access_key_id": ""}, S3_SECRETS, "Access Key ID is required."),
        ("s3", S3_KEYS, None, "Secret Access Key is required."),
        ("azure_blob", AZURE_KEY, None, "Account Key is required."),
        ("azure_blob", {**AZURE_SPN, "tenant_id": ""}, AZURE_SPN_SECRETS, "Tenant ID is required."),
        ("azure_blob", AZURE_SPN, None, "Client Secret is required."),
    ],
)
def test_a_strategy_missing_a_credential_names_it(code, parameters, secrets, message):
    with pytest.raises(ValueError, match=message):
        validate(code, parameters, secrets)


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({**S3_ROLE, "base_uri": "claims-bucket/monthly"}, "Base URI must be an S3 location"),
        ({**S3_ROLE, "base_uri": "s3://claims-bucket?versionId=1"}, "Base URI must be an S3 location"),
        ({**S3_ROLE, "base_uri": "s3://Claims_Bucket"}, "Base URI must name a valid bucket"),
        ({**S3_ROLE, "strategy": "session_token"}, "Choose a Connection Strategy."),
        ({**S3_ROLE, "strategy": ""}, "Connection Strategy is required."),
        # The allow-list and scope take the prefix as written while reads collapse it, so these
        # would save and then refuse every table.
        ({**S3_ROLE, "base_uri": "s3://claims-bucket//monthly"}, "Base URI cannot contain empty"),
        ({**S3_ROLE, "base_uri": "s3://claims-bucket/a/../monthly"}, "Base URI cannot contain empty"),
        ({**S3_ROLE, "base_uri": "s3://claims-bucket/monthly/*"}, "Base URI cannot contain a pattern"),
        ({**S3_ROLE, "region": ""}, "Region is required."),
    ],
)
def test_a_malformed_s3_connection_is_rejected(parameters, message):
    with pytest.raises(ValueError, match=message):
        validate("s3", parameters)


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({**AZURE_MI, "storage_account": "Claims-Acct"}, "Storage Account must be"),
        ({**AZURE_MI, "container": "a--b"}, "Container must be"),
        ({**AZURE_MI, "container": "-claims"}, "Container must be"),
        ({**AZURE_MI, "strategy": "password"}, "Choose a Connection Strategy."),
    ],
)
def test_a_malformed_azure_connection_is_rejected(parameters, message):
    with pytest.raises(ValueError, match=message):
        validate("azure_blob", parameters)


@pytest.mark.parametrize("base_uri", ["s3://claims-bucket/monthly/", "s3://claims-bucket"])
def test_a_trailing_slash_or_a_bucket_root_is_a_valid_base_uri(base_uri):
    validate("s3", {**S3_ROLE, "base_uri": base_uri})


def test_switching_strategy_drops_what_the_old_one_stored():
    parameters, secrets = DuckdbFlavorService().scrub_settings(
        {**AZURE_SPN, "strategy": "account_key"}, {**AZURE_SPN_SECRETS, **AZURE_KEY_SECRETS}, "azure_blob"
    )
    assert parameters == AZURE_KEY
    assert secrets == AZURE_KEY_SECRETS


def test_a_strategy_that_reads_no_secret_keeps_none():
    parameters, secrets = DuckdbFlavorService().scrub_settings(
        {**S3_KEYS, "strategy": "iam_role"}, S3_SECRETS, "s3"
    )
    assert parameters == S3_ROLE
    assert secrets is None


def test_a_database_code_is_not_scrubbed():
    parameters = {"database_file": "/data/db.duckdb"}
    assert DuckdbFlavorService().scrub_settings(parameters, None, "duckdb") == (parameters, None)


# -- secret statements --------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "parameters", "secrets"),
    [
        ("s3", S3_KEYS, S3_SECRETS),
        ("azure_blob", AZURE_KEY, AZURE_KEY_SECRETS),
        ("azure_blob", AZURE_SPN, AZURE_SPN_SECRETS),
    ],
)
def test_no_credential_reaches_the_sql_text(code, parameters, secrets):
    """DuckDB repeats the statement in its error text, so a credential in it would reach logs."""
    statement, binds = object_storage.STORES[code].create_secret_statement(parameters, secrets)
    for value in (*secrets.values(), parameters.get("access_key_id")):
        if value:
            assert value not in statement
            assert any(value in bound for bound in binds.values())
    assert "PERSISTENT" not in statement.upper()


@pytest.mark.parametrize(
    ("code", "parameters", "scope"),
    [("s3", S3_ROLE, "s3://claims-bucket/monthly/"), ("azure_blob", AZURE_MI, "az://claims/")],
)
def test_the_secret_is_scoped_to_the_base_location(code, parameters, scope):
    _, binds = object_storage.STORES[code].create_secret_statement(parameters, {})
    assert binds["scope"] == scope


def test_the_iam_role_strategy_refreshes_what_the_chain_found():
    statement, binds = object_storage.STORES["s3"].create_secret_statement(S3_ROLE, {})
    assert "PROVIDER credential_chain" in statement
    assert "REFRESH auto" in statement
    assert "CHAIN" not in statement
    assert binds == {"region": "us-east-1", "scope": "s3://claims-bucket/monthly/"}


@pytest.mark.parametrize("parameters", [S3_KEYS, S3_ROLE])
def test_a_dotted_bucket_is_addressed_by_path(parameters):
    dotted = {**parameters, "base_uri": "s3://claims.data.bucket/monthly"}
    statement, _ = object_storage.STORES["s3"].create_secret_statement(dotted, S3_SECRETS)
    assert "URL_STYLE 'path'" in statement


@pytest.mark.parametrize("parameters", [S3_KEYS, S3_ROLE])
def test_an_undotted_bucket_keeps_the_default_addressing(parameters):
    statement, _ = object_storage.STORES["s3"].create_secret_statement(parameters, S3_SECRETS)
    assert "URL_STYLE" not in statement


def test_managed_identity_also_reaches_workload_identity():
    statement, _ = object_storage.STORES["azure_blob"].create_secret_statement(AZURE_MI, {})
    assert "CHAIN 'managed_identity;workload_identity'" in statement


@pytest.mark.parametrize(
    ("code", "parameters", "expected"),
    [("s3", S3_KEYS, ("httpfs",)), ("s3", S3_ROLE, ("httpfs", "aws")), ("azure_blob", AZURE_MI, ("azure",))],
)
def test_each_strategy_loads_the_extension_that_reads_it(code, parameters, expected):
    assert object_storage.STORES[code].extensions(parameters) == expected


# -- engine ---------------------------------------------------------------------


@pytest.mark.parametrize("code", ["duckdb", "files", "s3", "azure_blob"])
def test_no_duckdb_code_can_persist_a_secret(code):
    params = resolve_connection_params(connection_params(code, {}))
    assert DuckdbFlavorService().get_connect_args(params)["config"]["allow_persistent_secrets"] is False


@pytest.mark.parametrize("code", ["duckdb", "files", "s3", "azure_blob"])
def test_the_engine_keeps_bound_values_out_of_its_errors(code):
    params = resolve_connection_params(connection_params(code, {}))
    assert DuckdbFlavorService().get_engine_args(params)["hide_parameters"] is True


def test_a_failed_statement_does_not_print_what_was_bound_into_it():
    service = DuckdbFlavorService()
    engine = service.create_engine(connection_params("s3", S3_KEYS, S3_SECRETS))
    try:
        with engine.connect() as connection, pytest.raises(Exception) as raised:
            connection.exec_driver_sql("SELECT * FROM no_such_table WHERE ? IS NOT NULL", ("s3-secret-value",))
    finally:
        engine.dispose()
    assert "s3-secret-value" not in str(raised.value)


# -- init ---------------------------------------------------------------------------


class RecordingConnection:
    """Stands in for a SQLAlchemy connection, recording statements in the order they run."""

    def __init__(self, fail_on: Callable[[str], Exception | None] = lambda _statement: None) -> None:
        self.statements: list[str] = []
        self.binds: list[dict | None] = []
        self.info: dict = {}
        self._fail_on = fail_on

    def execute(self, statement, binds=None):
        text_value = str(statement)
        self.statements.append(text_value)
        self.binds.append(binds)
        if error := self._fail_on(text_value):
            raise error
        return MagicMock()

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def test_credentials_are_registered_before_the_configuration_is_locked(monkeypatch):
    """A locked connection can neither load an extension nor, with external access closed,
    register a secret DuckDB would otherwise look for on disk."""
    monkeypatch.setattr(duckdb_flavor_service.settings, "DUCKDB_EXTENSION_DIRECTORY", "/dk/duckdb/extensions")
    connection = RecordingConnection()
    params = resolve_connection_params(connection_params("s3", S3_ROLE))

    DuckdbFlavorService().init(connection, params, [])

    order = [statement.split(" (")[0].split(" =")[0] for statement in connection.statements[1:]]
    assert order == [
        "SET TimeZone",
        "LOAD httpfs",
        "LOAD aws",
        "CREATE SECRET tg_storage",
        "SET allowed_directories",
        "SET enable_external_access",
        "SET lock_configuration",
    ]
    allow_list = next(statement for statement in connection.statements if "allowed_directories" in statement)
    assert allow_list.startswith("SET allowed_directories = ['s3://claims-bucket/monthly/', ")


def test_an_azure_connection_reads_through_the_curl_transport(monkeypatch):
    monkeypatch.setattr(duckdb_flavor_service.settings, "DUCKDB_EXTENSION_DIRECTORY", "/dk/duckdb/extensions")
    connection = RecordingConnection()
    DuckdbFlavorService().init(connection, resolve_connection_params(connection_params("azure_blob", AZURE_MI)), [])

    order = [statement.split(" (")[0].split(" =")[0] for statement in connection.statements[2:5]]
    assert order == ["LOAD azure", "SET azure_transport_option_type", "CREATE SECRET tg_storage"]
    assert "SET azure_transport_option_type = 'curl'" in connection.statements


def test_extensions_are_installed_only_where_none_are_bundled(monkeypatch):
    monkeypatch.setattr(duckdb_flavor_service.settings, "DUCKDB_EXTENSION_DIRECTORY", "")
    connection = RecordingConnection()
    DuckdbFlavorService().init(connection, resolve_connection_params(connection_params("azure_blob", AZURE_MI)), [])
    assert connection.statements[2:4] == ["INSTALL azure", "LOAD azure"]


def test_an_iam_role_that_finds_nothing_says_where_it_looked(monkeypatch):
    monkeypatch.setattr(duckdb_flavor_service.settings, "DUCKDB_EXTENSION_DIRECTORY", "/dk/duckdb/extensions")
    driver_error = duckdb.Error(
        "Secret Validation Failure: during `create` using the following:\nCredential Chain: 'config'\n"
    )
    connection = RecordingConnection(
        lambda statement: _wrapped(driver_error) if statement.startswith("CREATE SECRET") else None
    )

    with pytest.raises(DuckdbConnectionError) as raised:
        DuckdbFlavorService().init(connection, resolve_connection_params(connection_params("s3", S3_ROLE)), [])

    assert str(raised.value) == S3_NO_CREDENTIALS
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__


def _wrapped(error: Exception) -> Exception:
    """The error the way SQLAlchemy raises it, with the driver's exception on ``orig``."""
    wrapper = Exception("(duckdb.Error) wrapper text [parameters: ('s3-secret-value',)]")
    wrapper.orig = error  # type: ignore[attr-defined]
    return wrapper


def test_a_declaration_that_cannot_be_read_reports_the_store_in_plain_words(monkeypatch):
    monkeypatch.setattr(duckdb_flavor_service.settings, "DUCKDB_EXTENSION_DIRECTORY", "/dk/duckdb/extensions")
    driver_error = duckdb.Error("Failed to get token from ChainedTokenCredential.\n\nLINE 1: CREATE VIEW")
    connection = RecordingConnection(
        lambda statement: _wrapped(driver_error) if statement.startswith("CREATE VIEW") else None
    )
    service = DuckdbFlavorService()
    params = connection_params("azure_blob", AZURE_MI)
    declarations = [
        FileDeclaration(name="claims", uri="monthly/*.csv", format=FileFormat.CSV),
    ]

    service.init(connection, resolve_connection_params(params), declarations)

    assert service.declaration_failures(connection) == {
        "claims": "No managed identity was found. Managed Identity uses the identity of the environment "
        "running TestGen, such as an Azure VM or AKS pod."
    }


# -- the confinement DuckDB applies to object storage --------------------------------


def _locked_to(allowed: str) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(f"SET allowed_directories = ['{allowed}']")
    connection.execute("SET enable_external_access = false")
    connection.execute("SET lock_configuration = true")
    return connection


@pytest.mark.parametrize(
    "outside",
    ["s3://claims-bucket/monthly-archive/a.csv", "s3://other-bucket/monthly/a.csv", "/etc/hosts"],
)
def test_a_read_outside_the_base_location_is_refused(outside):
    connection = _locked_to("s3://claims-bucket/monthly/")
    with pytest.raises(duckdb.PermissionException):
        connection.execute(f"SELECT * FROM read_csv('{outside}')")


# -- test connection --------------------------------------------------------------


@pytest.mark.parametrize(("count", "expected"), [
    (0, "No files found under the base URI."),
    (1, "1 file found under the base URI."),
    (2500, "2,500 files found under the base URI."),
    (10_001, "More than 10,000 files found under the base URI."),
])
def test_a_storage_connection_reports_what_it_found(count, expected):
    connection = MagicMock()
    connection.execute.return_value.scalar.return_value = count

    details = DuckdbFlavorService().test_connection_details(
        connection, resolve_connection_params(connection_params("s3", S3_ROLE))
    )

    assert details == expected
    assert [str(call.args[0]) for call in connection.execute.call_args_list] == [
        "SELECT COUNT(*) AS file_ct FROM (SELECT 1 FROM glob('s3://claims-bucket/monthly/**') LIMIT 10001)"
    ]


def test_an_azure_connection_counts_under_the_container():
    connection = MagicMock()
    connection.execute.return_value.scalar.return_value = 3
    details = DuckdbFlavorService().test_connection_details(
        connection, resolve_connection_params(connection_params("azure_blob", AZURE_MI))
    )
    assert details == "3 files found under the container."


def test_a_credential_that_fails_on_first_use_fails_the_connection_test():
    connection = MagicMock()
    connection.execute.side_effect = _wrapped(duckdb.Error("Failed to get token from ChainedTokenCredential."))

    with pytest.raises(DuckdbConnectionError, match="No managed identity was found."):
        DuckdbFlavorService().test_connection_details(
            connection, resolve_connection_params(connection_params("azure_blob", AZURE_MI))
        )


# -- error wording ------------------------------------------------------------------

# Failure text as the stores returned it to DuckDB 1.5.5, trimmed to what the wording keys on.
_S3_BAD_KEY = (
    "HTTP Error: HTTP GET error reading 's3://bucket' in region 'us-east-1' (HTTP 403 Forbidden)\n\n"
    "InvalidAccessKeyId: The AWS Access Key Id you provided does not exist in our records."
)
_S3_DENIED = "HTTP Error: HTTP GET error reading 's3://bucket/x.csv' in region 'us-east-1' (HTTP 403 Forbidden)"
_S3_MISSING = "HTTP Error: HTTP GET error reading 's3://bucket/nope.csv' in region '' (HTTP 404 Not Found)"
_S3_ROLE_REJECTED = (
    "HTTP Error: HTTP GET error reading 's3://bucket' in region 'us-east-1' (HTTP 400 Bad Request)\n\n"
    "InvalidToken: The provided token is malformed or otherwise invalid."
)
_AZURE_BAD_KEY = (
    "IO Error: AzureBlobStorageFileSystem Read to az://ctr/** failed with AuthenticationFailed Reason Phrase: "
    "Server failed to authenticate the request."
)
_AZURE_BAD_SPN = (
    'GetToken(): error response: 400 Bad Request\n\n{"error":"invalid_request","error_description":'
    '"AADSTS900021: Requested tenant identifier is not valid. Trace ID: 52f0dd76"}'
)
_AZURE_NO_ACCOUNT = "Fail to get a new connection for: https://nope.blob.core.windows.net. Could not resolve hostname"


@pytest.mark.parametrize(
    ("code", "parameters", "raw", "expected"),
    [
        ("s3", S3_KEYS, _S3_BAD_KEY, "The access key was not accepted."),
        ("s3", S3_KEYS, _S3_DENIED, "Access was denied."),
        ("s3", S3_KEYS, _S3_MISSING, "The file was not found. To read the files in a folder, use a pattern"),
        ("s3", S3_ROLE, "Secret Validation Failure: during `create`", S3_NO_CREDENTIALS),
        ("s3", S3_ROLE, _S3_ROLE_REJECTED, "The credentials found by the credential chain were not accepted."),
        ("azure_blob", AZURE_KEY, _AZURE_BAD_KEY, "The account key was not accepted."),
        ("azure_blob", AZURE_SPN, _AZURE_BAD_SPN, "The service principal could not sign in. AADSTS900021:"),
        ("azure_blob", AZURE_MI, _AZURE_NO_ACCOUNT, "The storage account was not found."),
        (
            "azure_blob",
            AZURE_MI,
            "Invalid Input Error: Failed to parse http_proxy 'http://user:pass@proxy:3128' into a host and port",
            "The proxy configured for TestGen includes a username or password",
        ),
    ],
)
def test_store_failures_are_worded_for_the_person_who_configured_them(code, parameters, raw, expected):
    message = object_storage.STORES[code].storage_error_message(parameters, Exception(raw))
    assert message.startswith(expected)
    assert "Trace ID" not in message
    assert "user:pass" not in message


def test_an_unrecognized_failure_keeps_the_drivers_first_line():
    raw = "IO Error: something new\n\nLINE 1: SELECT * FROM read_csv('s3://bucket/x.csv')"
    assert object_storage.STORES["s3"].storage_error_message(S3_KEYS, Exception(raw)) == "IO Error: something new"
