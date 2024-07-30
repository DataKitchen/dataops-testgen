from abc import abstractmethod

from testgen import settings
from testgen.common.encrypt import DecryptText


class FlavorService:

    url = None
    connect_by_url = None
    username = None
    host = None
    port = None
    dbname = None
    flavor = None
    dbschema = None
    connect_by_key = None
    private_key = None
    private_key_passphrase = None
    catalog = None

    def init(self, connection_params: dict):
        self.url = connection_params.get("url", None)
        self.connect_by_url = connection_params.get("connect_by_url", False)
        self.username = connection_params.get("user")
        self.host = connection_params.get("host")
        self.port = connection_params.get("port")
        self.dbname = connection_params.get("dbname")
        self.flavor = connection_params.get("flavor")
        self.dbschema = connection_params.get("dbschema", None)
        self.connect_by_key = connection_params.get("connect_by_key", False)
        self.catalog = connection_params.get("catalog", None)

        private_key = connection_params.get("private_key", None)
        if isinstance(private_key, memoryview):
            private_key = DecryptText(private_key)
        self.private_key = private_key

        private_key_passphrase = connection_params.get("private_key_passphrase", None)
        if isinstance(private_key_passphrase, memoryview):
            private_key_passphrase = DecryptText(private_key_passphrase)
        self.private_key_passphrase = private_key_passphrase

    def override_user(self, user_override: str):
        self.username = user_override

    def get_db_name(self) -> str:
        return self.dbname

    def is_connect_by_key(self) -> str:
        return self.connect_by_key

    def get_connect_args(self, is_password_overwritten: bool = False):  # NOQA ARG002
        if settings.SKIP_DATABASE_CERTIFICATE_VERIFICATION:
            return {"TrustServerCertificate": "yes"}
        return {}

    def get_concat_operator(self):
        return "||"

    def get_connection_string(self, strPW, is_password_overwritten: bool = False):
        if self.connect_by_url:
            header = self.get_connection_string_head(strPW)
            url = header + self.url
            return url
        else:
            return self.get_connection_string_from_fields(strPW, is_password_overwritten)

    @abstractmethod
    def get_connection_string_from_fields(self, strPW, is_password_overwritten: bool = False):
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    def get_connection_string_head(self, strPW):
        raise NotImplementedError("Subclasses must implement this method")
