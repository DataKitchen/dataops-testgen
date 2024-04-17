from abc import abstractmethod

from testgen import settings


class FlavorService:
    def get_connect_args(self):
        if settings.SKIP_DATABASE_CERTIFICATE_VERIFICATION:
            return {"TrustServerCertificate": "yes"}
        return {}

    def get_concat_operator(self):
        return "||"

    def get_connection_string(self, dctCredentials, strPW):
        if dctCredentials["connect_by_url"]:
            header = self.get_connection_string_head(dctCredentials, strPW)
            url = header + dctCredentials["url"]
            return url
        else:
            return self.get_connection_string_from_fields(dctCredentials, strPW)

    @abstractmethod
    def get_connection_string_from_fields(self, dctCredentials, strPW):
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    def get_connection_string_head(self, dctCredentials, strPW):
        raise NotImplementedError("Subclasses must implement this method")
