"""Object storage for the DuckDB flavor — the Amazon S3 and Azure Blob Storage connection codes.

Each code reads the same file declarations as a connection on a mounted path. What differs is
where the base location comes from, which DuckDB extension reads it, and the secret that
authenticates the reads. Each store is an ``ObjectStore`` subclass registered in ``STORES`` under
its connection code. Secrets are registered for the life of one DuckDB connection and never
persisted: the engine is opened with persistent secrets disabled, and every credential reaches
``CREATE SECRET`` as a bound parameter rather than as SQL text.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, ClassVar

from testgen.common.database.flavor.flavor_service import ConnectionField
from testgen.common.flavors import SqlFlavorCode

STRATEGY_PARAMETER = "strategy"

# Amazon S3
BASE_URI_PARAMETER = "base_uri"
REGION_PARAMETER = "region"
ACCESS_KEY_ID_PARAMETER = "access_key_id"
SECRET_ACCESS_KEY_SECRET = "secret_access_key"  # noqa: S105 — a key name, not a credential

# Azure Blob Storage
STORAGE_ACCOUNT_PARAMETER = "storage_account"
CONTAINER_PARAMETER = "container"
CLIENT_ID_PARAMETER = "client_id"
TENANT_ID_PARAMETER = "tenant_id"
ACCOUNT_KEY_SECRET = "account_key"  # noqa: S105 — a key name, not a credential
CLIENT_SECRET_SECRET = "client_secret"  # noqa: S105 — a key name, not a credential

SECRET_NAME = "tg_storage"  # noqa: S105 — the name DuckDB files the secret under


class S3Strategy(StrEnum):
    ACCESS_KEYS = "access_keys"
    IAM_ROLE = "iam_role"


class AzureBlobStrategy(StrEnum):
    ACCOUNT_KEY = "account_key"
    MANAGED_IDENTITY = "managed_identity"
    SERVICE_PRINCIPAL = "service_principal"


_StrategyFields = tuple[tuple[str, ...], tuple[str, ...]]


def _text(values: dict[str, Any] | None, key: str) -> str:
    value = (values or {}).get(key)
    return value.strip() if isinstance(value, str) else ""


class ObjectStore(ABC):
    """One object-storage connection code: its fields, its strategies, and how DuckDB reaches it."""

    parameters_schema: ClassVar[tuple[ConnectionField, ...]]
    secrets_schema: ClassVar[tuple[ConnectionField, ...]]
    strategies: ClassVar[type[StrEnum]]
    # The parameters and secrets each strategy reads.
    strategy_fields: ClassVar[dict[str, _StrategyFields]]
    # How messages name the base location, as in "found under the container".
    location_label: ClassVar[str]
    # Statements run once the extensions are loaded, before the secret is created.
    setup_statements: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def base_location(self, parameters: dict[str, Any] | None) -> str:
        """The URI every declaration on the connection resolves against, without a trailing slash."""

    @abstractmethod
    def validate_location(self, parameters: dict[str, Any] | None) -> None:
        """Raise ``ValueError`` when the location fields break the provider's naming rules."""

    @abstractmethod
    def extensions(self, parameters: dict[str, Any] | None) -> tuple[str, ...]:
        """The DuckDB extensions a connection reads through, in load order."""

    @abstractmethod
    def secret_options(
        self, parameters: dict[str, Any] | None, secrets: dict[str, Any] | None
    ) -> tuple[str, dict[str, str]]:
        """The ``CREATE SECRET`` options other than the scope, and the values bound into them."""

    @abstractmethod
    def error_message(self, parameters: dict[str, Any] | None, raw: str) -> str | None:
        """User-facing wording for a failure this store reports, or ``None`` when it is not one of them."""

    def strategy(self, parameters: dict[str, Any] | None) -> str:
        return _text(parameters, STRATEGY_PARAMETER)

    def scrub(
        self, parameters: dict[str, Any] | None, secrets: dict[str, Any] | None
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The parameters and secrets with whatever the chosen strategy does not read removed."""
        strategy_parameters, strategy_secrets = self.strategy_fields.get(self.strategy(parameters), ((), ()))
        always = {field.key for field in self.parameters_schema if field.required}
        kept_parameters = {
            key: value for key, value in (parameters or {}).items() if key in always or key in strategy_parameters
        }
        kept_secrets = {key: value for key, value in (secrets or {}).items() if key in strategy_secrets}
        return kept_parameters or None, kept_secrets or None

    def validate(self, parameters: dict[str, Any] | None, secrets: dict[str, Any] | None) -> None:
        """Raise ``ValueError`` naming the first field the connection gets wrong for its strategy."""
        if self.strategy(parameters) not in set(self.strategies):
            raise ValueError("Choose a Connection Strategy.")
        self.validate_location(parameters)

        required_parameters, required_secrets = self.strategy_fields[self.strategy(parameters)]
        labels = {field.key: field.label for field in (*self.parameters_schema, *self.secrets_schema)}
        for key in required_parameters:
            if not _text(parameters, key):
                raise ValueError(f"{labels[key]} is required.")
        for key in required_secrets:
            if not _text(secrets, key):
                raise ValueError(f"{labels[key]} is required.")

    def create_secret_statement(
        self, parameters: dict[str, Any] | None, secrets: dict[str, Any] | None
    ) -> tuple[str, dict[str, str]]:
        """The ``CREATE SECRET`` for a connection and the values bound into it.

        Credentials travel only as bind values, so they never appear in the SQL text, which DuckDB
        repeats in its error messages.
        """
        options, binds = self.secret_options(parameters, secrets)
        binds = {**binds, "scope": self.base_location(parameters) + "/"}
        return f"CREATE SECRET {SECRET_NAME} ({options}, SCOPE :scope)", binds

    def storage_error_message(self, parameters: dict[str, Any] | None, error: Exception) -> str:
        """A message for a failure reading object storage, worded for the person who configured it.

        ``error`` should be the driver's own exception rather than SQLAlchemy's wrapper, whose text
        carries the bound values.
        """
        raw = str(error)
        lowered = raw.lower()
        if "failed to parse http_proxy" in lowered or "failed to parse https_proxy" in lowered:
            return (
                "The proxy configured for TestGen includes a username or password, which cannot be used to "
                "reach object storage."
            )
        if message := self.error_message(parameters, raw):
            return message
        # The driver's first line, without the statement DuckDB echoes after it.
        return raw.split("\n")[0].strip()


class S3Store(ObjectStore):
    parameters_schema = (
        ConnectionField(key=BASE_URI_PARAMETER, label="Base URI", required=True),
        ConnectionField(key=REGION_PARAMETER, label="Region", required=True),
        ConnectionField(key=STRATEGY_PARAMETER, label="Connection Strategy", required=True),
        ConnectionField(key=ACCESS_KEY_ID_PARAMETER, label="Access Key ID"),
    )
    secrets_schema = (ConnectionField(key=SECRET_ACCESS_KEY_SECRET, label="Secret Access Key"),)
    strategies = S3Strategy
    strategy_fields: ClassVar[dict[str, _StrategyFields]] = {
        S3Strategy.ACCESS_KEYS: ((ACCESS_KEY_ID_PARAMETER,), (SECRET_ACCESS_KEY_SECRET,)),
        S3Strategy.IAM_ROLE: ((), ()),
    }
    location_label = "the base URI"

    # Rules the provider enforces on the names, checked here so a typo is reported against the
    # field rather than as a failed request.
    _BASE_URI = re.compile(r"^s3://(?P<bucket>[^/?#]+)(?P<prefix>/[^?#]*)?$")
    _BUCKET_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")

    def base_location(self, parameters: dict[str, Any] | None) -> str:
        return _text(parameters, BASE_URI_PARAMETER).rstrip("/")

    def validate_location(self, parameters: dict[str, Any] | None) -> None:
        match = self._BASE_URI.match(_text(parameters, BASE_URI_PARAMETER))
        if not match:
            raise ValueError("Base URI must be an S3 location, such as s3://bucket/prefix.")
        if not self._BUCKET_NAME.match(match["bucket"]):
            raise ValueError(
                "Base URI must name a valid bucket: 3 to 63 lowercase letters, numbers, dots and hyphens."
            )
        # The allow-list and the secret's scope take the prefix as written, and every read is
        # resolved with its segments collapsed, so a prefix that collapses differently matches
        # neither and every table is refused.
        # Trailing slashes are dropped from the base location, so only they are allowed to repeat.
        prefix = (match["prefix"] or "").removeprefix("/").rstrip("/")
        if prefix and any(segment in ("", ".", "..") for segment in prefix.split("/")):
            raise ValueError("Base URI cannot contain empty, . or .. path segments.")
        if any(character in prefix for character in "*?["):
            raise ValueError("Base URI cannot contain a pattern. Put patterns on the tables instead.")

    def extensions(self, parameters: dict[str, Any] | None) -> tuple[str, ...]:
        if self.strategy(parameters) == S3Strategy.IAM_ROLE:
            # The credential chain provider lives in the aws extension rather than in httpfs.
            return ("httpfs", "aws")
        return ("httpfs",)

    def secret_options(
        self, parameters: dict[str, Any] | None, secrets: dict[str, Any] | None
    ) -> tuple[str, dict[str, str]]:
        binds = {"region": _text(parameters, REGION_PARAMETER)}
        # A bucket name with a dot becomes more than one host label under virtual-hosted
        # addressing, which the *.s3.amazonaws.com certificate does not cover.
        match = self._BASE_URI.match(self.base_location(parameters))
        url_style = ", URL_STYLE 'path'" if match and "." in match["bucket"] else ""
        if self.strategy(parameters) == S3Strategy.IAM_ROLE:
            # The default chain is the AWS SDK's: environment, shared files, web identity, the
            # container credentials endpoint, then instance metadata. REFRESH re-resolves it when
            # the credentials it found expire, which temporary ones do within hours.
            return f"TYPE s3, PROVIDER credential_chain, REFRESH auto, REGION :region{url_style}", binds
        binds |= {
            "key_id": _text(parameters, ACCESS_KEY_ID_PARAMETER),
            "secret": _text(secrets, SECRET_ACCESS_KEY_SECRET),
        }
        return f"TYPE s3, KEY_ID :key_id, SECRET :secret, REGION :region{url_style}", binds

    def error_message(self, parameters: dict[str, Any] | None, raw: str) -> str | None:  # noqa: ARG002
        lowered = raw.lower()
        if "secret validation failure" in lowered:
            return (
                "No credentials were found. The credential chain looks for AWS credentials in the "
                "environment running TestGen. From inside a container, an EC2 instance role requires the "
                "instance metadata hop limit to be 2."
            )
        if "invalidaccesskeyid" in lowered or "signaturedoesnotmatch" in lowered:
            return "The access key was not accepted. Check the Access Key ID and Secret Access Key."
        if "expiredtoken" in lowered:
            return "The credentials found by the credential chain have expired."
        if "invalidtoken" in lowered:
            return "The credentials found by the credential chain were not accepted."
        if "nosuchbucket" in lowered:
            return "The bucket was not found."
        if "permanentredirect" in lowered or "authorizationheadermalformed" in lowered or "(http 301" in lowered:
            return "The bucket is in a different region than the one configured."
        if "(http 403" in lowered:
            return "Access was denied. The credentials must allow listing and reading objects under the base URI."
        if "(http 404" in lowered:
            # A declaration naming a prefix is read as one object, which the store reports as missing.
            return "The file was not found. To read the files in a folder, use a pattern such as sales/*.csv."
        return None


class AzureBlobStore(ObjectStore):
    parameters_schema = (
        ConnectionField(key=STORAGE_ACCOUNT_PARAMETER, label="Storage Account", required=True),
        ConnectionField(key=CONTAINER_PARAMETER, label="Container", required=True),
        ConnectionField(key=STRATEGY_PARAMETER, label="Connection Strategy", required=True),
        ConnectionField(key=CLIENT_ID_PARAMETER, label="Client ID"),
        ConnectionField(key=TENANT_ID_PARAMETER, label="Tenant ID"),
    )
    secrets_schema = (
        ConnectionField(key=ACCOUNT_KEY_SECRET, label="Account Key"),
        ConnectionField(key=CLIENT_SECRET_SECRET, label="Client Secret"),
    )
    strategies = AzureBlobStrategy
    strategy_fields: ClassVar[dict[str, _StrategyFields]] = {
        AzureBlobStrategy.ACCOUNT_KEY: ((), (ACCOUNT_KEY_SECRET,)),
        AzureBlobStrategy.MANAGED_IDENTITY: ((), ()),
        AzureBlobStrategy.SERVICE_PRINCIPAL: ((CLIENT_ID_PARAMETER, TENANT_ID_PARAMETER), (CLIENT_SECRET_SECRET,)),
    }
    location_label = "the container"
    # The default transport cannot find the system CA bundle on some Linux distributions, Debian
    # and Ubuntu among them, so every sign-in fails. The curl transport searches the standard paths.
    setup_statements = ("SET azure_transport_option_type = 'curl'",)

    # Rules the provider enforces on the names, checked here so a typo is reported against the
    # field rather than as a failed request.
    _STORAGE_ACCOUNT_NAME = re.compile(r"^[a-z0-9]{3,24}$")
    _CONTAINER_NAME = re.compile(r"^(?!.*--)[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
    _AADSTS_MESSAGE = re.compile(r"(AADSTS\d+: [^.\"]*\.)")

    def base_location(self, parameters: dict[str, Any] | None) -> str:
        container = _text(parameters, CONTAINER_PARAMETER)
        return f"az://{container}" if container else ""

    def validate_location(self, parameters: dict[str, Any] | None) -> None:
        if not self._STORAGE_ACCOUNT_NAME.match(_text(parameters, STORAGE_ACCOUNT_PARAMETER)):
            raise ValueError("Storage Account must be 3 to 24 lowercase letters and numbers.")
        if not self._CONTAINER_NAME.match(_text(parameters, CONTAINER_PARAMETER)):
            raise ValueError(
                "Container must be 3 to 63 lowercase letters, numbers and single hyphens, "
                "starting and ending with a letter or number."
            )

    def extensions(self, parameters: dict[str, Any] | None) -> tuple[str, ...]:  # noqa: ARG002
        return ("azure",)

    def secret_options(
        self, parameters: dict[str, Any] | None, secrets: dict[str, Any] | None
    ) -> tuple[str, dict[str, str]]:
        account = _text(parameters, STORAGE_ACCOUNT_PARAMETER)
        strategy = self.strategy(parameters)
        if strategy == AzureBlobStrategy.ACCOUNT_KEY:
            connection_string = (
                f"DefaultEndpointsProtocol=https;AccountName={account};"
                f"AccountKey={_text(secrets, ACCOUNT_KEY_SECRET)};EndpointSuffix=core.windows.net"
            )
            return "TYPE azure, CONNECTION_STRING :connection_string", {"connection_string": connection_string}
        if strategy == AzureBlobStrategy.SERVICE_PRINCIPAL:
            return (
                "TYPE azure, PROVIDER service_principal, TENANT_ID :tenant_id, CLIENT_ID :client_id, "
                "CLIENT_SECRET :client_secret, ACCOUNT_NAME :account"
            ), {
                "tenant_id": _text(parameters, TENANT_ID_PARAMETER),
                "client_id": _text(parameters, CLIENT_ID_PARAMETER),
                "client_secret": _text(secrets, CLIENT_SECRET_SECRET),
                "account": account,
            }
        # Workload identity is how a managed identity reaches a pod on AKS.
        return (
            "TYPE azure, PROVIDER credential_chain, CHAIN 'managed_identity;workload_identity', ACCOUNT_NAME :account",
            {"account": account},
        )

    def error_message(self, parameters: dict[str, Any] | None, raw: str) -> str | None:
        lowered = raw.lower()
        if "chainedtokencredential" in lowered:
            return (
                "No managed identity was found. Managed Identity uses the identity of the environment "
                "running TestGen, such as an Azure VM or AKS pod."
            )
        if aadsts := self._AADSTS_MESSAGE.search(raw):
            return f"The service principal could not sign in. {aadsts.group(1)}"
        if "could not resolve hostname" in lowered:
            return "The storage account was not found."
        if "containernotfound" in lowered:
            return "The container was not found."
        if "authenticationfailed" in lowered:
            if self.strategy(parameters) == AzureBlobStrategy.ACCOUNT_KEY:
                return "The account key was not accepted."
            return "The credentials were not accepted."
        if "authorizationpermissionmismatch" in lowered or "authorizationfailure" in lowered:
            return (
                "Access was denied. The identity needs a role that can list and read blobs in the "
                "container, such as Storage Blob Data Reader."
            )
        if "blobnotfound" in lowered:
            return "The file was not found. To read the files in a folder, use a pattern such as sales/*.csv."
        return None


STORES: dict[str, ObjectStore] = {
    SqlFlavorCode.S3: S3Store(),
    SqlFlavorCode.AZURE_BLOB: AzureBlobStore(),
}


def store_for(sql_flavor_code: str | None) -> ObjectStore | None:
    """The object store a connection code reads, or ``None`` for a code that reads no object storage."""
    return STORES.get(sql_flavor_code) if sql_flavor_code else None
