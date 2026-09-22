import smtplib
import ssl
from unittest.mock import ANY, call, patch

import pytest

from testgen.common.notifications.base import (
    MANDATORY_SETTINGS,
    SMTP_TIMEOUT_SECONDS,
    BaseEmailTemplate,
    EmailTemplateException,
    smtp_configured,
)
from testgen.settings import SMTPSecurity

pytestmark = pytest.mark.unit


class TestEmailTemplate(BaseEmailTemplate):

    def get_subject_template(self) -> str:
        return "{{project}}: Test execution finished"

    def get_body_template(self) -> str:
        return "<html><body><h1>DataKitchen TestGen</h1><p>Hi, {{user}}!</p></body></html>"


@pytest.fixture
def smtp_mock():
    with patch("testgen.common.notifications.base.smtplib.SMTP_SSL") as mock:
        yield mock


@pytest.fixture
def smtp_plain_mock():
    with patch("testgen.common.notifications.base.smtplib.SMTP") as mock:
        yield mock


@pytest.fixture
def def_settings():
    with patch("testgen.common.notifications.base.settings") as mock:
        mock.EMAIL_FROM_ADDRESS = "from@email"
        mock.SMTP_ENDPOINT = "smtp-endpoint"
        mock.SMTP_PORT = 333
        mock.SMTP_USERNAME = "smtp-user"
        mock.SMTP_PASSWORD = "smtp-pass"  # noqa: S105
        # settings.py reads this through getenv, so it is a plain string, not SMTPSecurity.
        mock.SMTP_SECURITY = "ssl"
        mock.SMTP_CLIENT_CERT_FILE = ""
        mock.SMTP_CLIENT_KEY_FILE = ""
        mock.SMTP_CLIENT_KEY_PASSWORD = ""
        yield mock


@pytest.fixture
def client_certificate(tmp_path):
    """A certificate and key on disk, as the settings name them by path."""
    cert, key = tmp_path / "client.crt", tmp_path / "client.key"
    cert.write_text("-----BEGIN CERTIFICATE-----\n")
    key.write_text("-----BEGIN PRIVATE KEY-----\n")
    return str(cert), str(key)


@pytest.fixture
def template(smtp_mock, def_settings):
    yield TestEmailTemplate()


@pytest.fixture
def send_args():
    return ["test@data.kitchen"], {"project": "Test Project", "user": "Test user"}


def test_send_email(smtp_mock, template, send_args, def_settings):
    template.send(*send_args)

    smtp_mock.assert_has_calls(
        [
            call("smtp-endpoint", 333, context=ANY, timeout=SMTP_TIMEOUT_SECONDS),
            call().__enter__().login("smtp-user", "smtp-pass"),
            call().__enter__().sendmail("from@email", ["test@data.kitchen"], ANY)
        ],
        any_order=True,
    )
    email_body = smtp_mock().__enter__().sendmail.call_args_list[0][0][2]
    assert "<h1>DataKitchen TestGen</h1>" in email_body
    assert "Subject: Test Project: Test execution finished" in email_body
    assert "<p>Hi, Test user!</p>" in email_body


@pytest.mark.parametrize("missing", MANDATORY_SETTINGS)
def test_settings_validation(missing, template, def_settings, send_args):
    setattr(def_settings, missing, None)
    with pytest.raises(EmailTemplateException, match="Invalid or insufficient email/SMTP settings"):
        template.send(*send_args)


def test_send_email_over_starttls(smtp_plain_mock, template, send_args, def_settings):
    def_settings.SMTP_SECURITY = "starttls"

    template.send(*send_args)

    smtp_plain_mock.assert_has_calls(
        [
            call("smtp-endpoint", 333, timeout=SMTP_TIMEOUT_SECONDS),
            call().starttls(context=ANY),
            call().__enter__().login("smtp-user", "smtp-pass"),
            call().__enter__().sendmail("from@email", ["test@data.kitchen"], ANY),
        ],
        any_order=True,
    )


def test_send_email_without_encryption(smtp_plain_mock, template, send_args, def_settings):
    def_settings.SMTP_SECURITY = "none"

    template.send(*send_args)

    smtp_plain_mock.assert_called_once_with("smtp-endpoint", 333, timeout=SMTP_TIMEOUT_SECONDS)
    smtp_plain_mock.return_value.starttls.assert_not_called()
    smtp_plain_mock.assert_has_calls(
        [call().__enter__().sendmail("from@email", ["test@data.kitchen"], ANY)],
        any_order=True,
    )


def test_send_email_ssl_does_not_use_plain_smtp(smtp_mock, smtp_plain_mock, template, send_args, def_settings):
    template.send(*send_args)

    smtp_mock.assert_called_once_with("smtp-endpoint", 333, context=ANY, timeout=SMTP_TIMEOUT_SECONDS)
    smtp_plain_mock.assert_not_called()


@pytest.mark.parametrize("value", ("tls", "STARTTLS ", "", "yes"))
def test_unrecognized_security_setting(value, template, def_settings, send_args, caplog):
    def_settings.SMTP_SECURITY = value

    with pytest.raises(EmailTemplateException, match="Invalid or insufficient email/SMTP settings"):
        template.send(*send_args)

    assert "TG_SMTP_SECURITY" in caplog.text
    assert "ssl, starttls, none" in caplog.text


def test_every_security_value_is_accepted(smtp_mock, smtp_plain_mock, template, send_args, def_settings):
    for security in SMTPSecurity:
        def_settings.SMTP_SECURITY = str(security)
        template.send(*send_args)


def test_starttls_failure_closes_the_connection(smtp_plain_mock, template, send_args, def_settings):
    def_settings.SMTP_SECURITY = "starttls"
    smtp_plain_mock.return_value.starttls.side_effect = ssl.SSLError("handshake failed")

    with pytest.raises(EmailTemplateException, match="Failed sending email notifications"):
        template.send(*send_args)

    smtp_plain_mock.return_value.close.assert_called_once()


def test_handshake_failure_suggests_starttls(smtp_mock, template, send_args, def_settings, caplog):
    smtp_mock.side_effect = ssl.SSLError("[SSL: WRONG_VERSION_NUMBER] wrong version number")

    with pytest.raises(EmailTemplateException, match="Failed sending email notifications"):
        template.send(*send_args)

    assert "smtp-endpoint:333 did not complete a TLS handshake" in caplog.text
    assert "TG_SMTP_SECURITY=starttls" in caplog.text


def test_plaintext_rejection_suggests_ssl(smtp_plain_mock, template, send_args, def_settings, caplog):
    def_settings.SMTP_SECURITY = "starttls"
    smtp_plain_mock.side_effect = smtplib.SMTPServerDisconnected("connection closed")

    with pytest.raises(EmailTemplateException, match="Failed sending email notifications"):
        template.send(*send_args)

    assert "smtp-endpoint:333 did not accept a plaintext connection" in caplog.text
    assert "TG_SMTP_SECURITY=ssl" in caplog.text


def test_authentication_failure_gets_no_transport_suggestion(smtp_mock, template, send_args, def_settings, caplog):
    smtp_mock.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPAuthenticationError(
        535, "authentication failed"
    )

    with pytest.raises(EmailTemplateException, match="Failed sending email notifications"):
        template.send(*send_args)

    assert "TG_SMTP_SECURITY" not in caplog.text


def test_missing_starttls_support_suggests_alternatives(smtp_plain_mock, template, send_args, def_settings, caplog):
    def_settings.SMTP_SECURITY = "starttls"
    smtp_plain_mock.return_value.starttls.side_effect = smtplib.SMTPNotSupportedError(
        "STARTTLS extension not supported by server."
    )

    with pytest.raises(EmailTemplateException, match="Failed sending email notifications"):
        template.send(*send_args)

    assert "does not offer STARTTLS" in caplog.text
    assert "TG_SMTP_SECURITY=none" in caplog.text
    smtp_plain_mock.return_value.login.assert_not_called()


@pytest.mark.parametrize("security", ("ssl", "starttls", "none"))
def test_every_transport_bounds_the_connection(security, smtp_mock, smtp_plain_mock, template, send_args, def_settings):
    def_settings.SMTP_SECURITY = security

    template.send(*send_args)

    constructor = smtp_mock if security == "ssl" else smtp_plain_mock
    assert constructor.call_args.kwargs["timeout"] == SMTP_TIMEOUT_SECONDS


def test_sends_without_credentials(smtp_plain_mock, template, send_args, def_settings):
    def_settings.SMTP_SECURITY = "starttls"
    def_settings.SMTP_USERNAME = None
    def_settings.SMTP_PASSWORD = None

    template.send(*send_args)

    smtp_plain_mock.return_value.__enter__.return_value.login.assert_not_called()
    smtp_plain_mock.assert_has_calls(
        [call().__enter__().sendmail("from@email", ["test@data.kitchen"], ANY)],
        any_order=True,
    )


@pytest.mark.parametrize("present", ("SMTP_USERNAME", "SMTP_PASSWORD"))
def test_half_configured_credentials_are_rejected(present, template, def_settings, send_args, caplog):
    for name in ("SMTP_USERNAME", "SMTP_PASSWORD"):
        setattr(def_settings, name, "value" if name == present else None)

    with pytest.raises(EmailTemplateException, match="Invalid or insufficient email/SMTP settings"):
        template.send(*send_args)

    assert "only one of TG_SMTP_USERNAME and TG_SMTP_PASSWORD is set" in caplog.text


def test_credentials_without_encryption_warn(smtp_plain_mock, template, send_args, def_settings, caplog):
    def_settings.SMTP_SECURITY = "none"

    template.send(*send_args)

    assert "over an unencrypted connection" in caplog.text


def test_no_warning_when_credentials_are_encrypted(smtp_plain_mock, template, send_args, def_settings, caplog):
    def_settings.SMTP_SECURITY = "starttls"

    template.send(*send_args)

    assert "over an unencrypted connection" not in caplog.text


def test_missing_auth_support_suggests_clearing_credentials(
    smtp_plain_mock, template, send_args, def_settings, caplog
):
    def_settings.SMTP_SECURITY = "starttls"
    smtp_plain_mock.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPNotSupportedError(
        "SMTP AUTH extension not supported by server."
    )

    with pytest.raises(EmailTemplateException, match="Failed sending email notifications"):
        template.send(*send_args)

    assert "offers no AUTH command" in caplog.text
    assert "Clear TG_SMTP_USERNAME and TG_SMTP_PASSWORD" in caplog.text
    # the STARTTLS hint must not fire: the server offered STARTTLS, it withheld AUTH
    assert "does not offer STARTTLS" not in caplog.text


@pytest.mark.parametrize(
    ("security", "username", "password", "sendable"),
    (
        ("ssl", "u", "p", True),
        ("ssl", None, None, True),
        ("starttls", "u", "p", True),
        ("starttls", None, None, True),
        ("none", None, None, True),
        ("ssl", "u", None, False),
        ("ssl", None, "p", False),
        ("tls", "u", "p", False),
        (None, "u", "p", False),
    ),
)
def test_configured_gate_agrees_with_validation(
    security, username, password, sendable, template, def_settings, send_args, smtp_mock, smtp_plain_mock
):
    def_settings.SMTP_SECURITY = security
    def_settings.SMTP_USERNAME = username
    def_settings.SMTP_PASSWORD = password

    assert smtp_configured() is sendable

    if sendable:
        template.send(*send_args)
    else:
        with pytest.raises(EmailTemplateException, match="Invalid or insufficient email/SMTP settings"):
            template.send(*send_args)


def test_all_problems_are_reported_together(template, def_settings, send_args, caplog):
    def_settings.SMTP_SECURITY = "tls"
    def_settings.SMTP_USERNAME = "u"
    def_settings.SMTP_PASSWORD = None
    def_settings.SMTP_ENDPOINT = None

    with pytest.raises(EmailTemplateException, match="Invalid or insufficient email/SMTP settings"):
        template.send(*send_args)

    assert "TG_SMTP_ENDPOINT" in caplog.text
    assert "TG_SMTP_SECURITY is set to 'tls'" in caplog.text
    assert "only one of TG_SMTP_USERNAME and TG_SMTP_PASSWORD is set" in caplog.text


def test_client_certificate_is_presented(smtp_mock, template, send_args, def_settings, client_certificate):
    cert, key = client_certificate
    def_settings.SMTP_CLIENT_CERT_FILE = cert
    def_settings.SMTP_CLIENT_KEY_FILE = key
    def_settings.SMTP_CLIENT_KEY_PASSWORD = "secret"  # noqa: S105

    with patch.object(ssl.SSLContext, "load_cert_chain") as load:
        template.send(*send_args)

    load.assert_called_once_with(cert, key, "secret")


def test_no_client_certificate_loads_nothing(smtp_mock, template, send_args, def_settings):
    with patch.object(ssl.SSLContext, "load_cert_chain") as load:
        template.send(*send_args)

    load.assert_not_called()


def test_client_certificate_without_passphrase_passes_none(
    smtp_mock, template, send_args, def_settings, client_certificate
):
    cert, key = client_certificate
    def_settings.SMTP_CLIENT_CERT_FILE = cert
    def_settings.SMTP_CLIENT_KEY_FILE = key

    with patch.object(ssl.SSLContext, "load_cert_chain") as load:
        template.send(*send_args)

    load.assert_called_once_with(cert, key, None)


@pytest.mark.parametrize("present", ("SMTP_CLIENT_CERT_FILE", "SMTP_CLIENT_KEY_FILE"))
def test_half_configured_client_certificate_is_rejected(
    present, template, def_settings, send_args, caplog, client_certificate
):
    for name, value in zip(("SMTP_CLIENT_CERT_FILE", "SMTP_CLIENT_KEY_FILE"), client_certificate, strict=True):
        setattr(def_settings, name, value if name == present else "")

    with pytest.raises(EmailTemplateException, match="Invalid or insufficient email/SMTP settings"):
        template.send(*send_args)

    assert "only one of TG_SMTP_CLIENT_CERT_FILE and TG_SMTP_CLIENT_KEY_FILE is set" in caplog.text
    assert smtp_configured() is False


def test_missing_client_certificate_file_is_rejected(template, def_settings, send_args, caplog, tmp_path):
    def_settings.SMTP_CLIENT_CERT_FILE = str(tmp_path / "absent.crt")
    def_settings.SMTP_CLIENT_KEY_FILE = str(tmp_path / "absent.key")

    with pytest.raises(EmailTemplateException, match="Invalid or insufficient email/SMTP settings"):
        template.send(*send_args)

    assert "client certificate files do not exist" in caplog.text
    assert "absent.crt" in caplog.text
    assert "absent.key" in caplog.text


def test_client_certificate_without_tls_is_rejected(
    template, def_settings, send_args, caplog, client_certificate
):
    def_settings.SMTP_CLIENT_CERT_FILE, def_settings.SMTP_CLIENT_KEY_FILE = client_certificate
    def_settings.SMTP_SECURITY = "none"

    with pytest.raises(EmailTemplateException, match="Invalid or insufficient email/SMTP settings"):
        template.send(*send_args)

    assert "opens no TLS connection to present it on" in caplog.text
    assert smtp_configured() is False
