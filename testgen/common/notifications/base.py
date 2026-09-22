import functools
import inspect
import logging
import operator
import re
import smtplib
import ssl
from collections.abc import Mapping
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from pybars import Compiler

from testgen import settings
from testgen.settings import SMTPSecurity

LOG = logging.getLogger(__name__)

MANDATORY_SETTINGS = (
    "EMAIL_FROM_ADDRESS",
    "SMTP_ENDPOINT",
    "SMTP_PORT",
)

CREDENTIAL_SETTINGS = (
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
)
"""Optional as a pair. A relay that authorizes by source address or client certificate
offers no AUTH command, and authenticating against one fails the send."""

SMTP_TIMEOUT_SECONDS = 30
"""Bounds every read on the SMTP connection. Without it a server that accepts the
connection and then stops responding holds the sending job open indefinitely."""


def smtp_settings_problems() -> list[str]:
    """Every reason the configured settings cannot send email, empty when they can."""
    problems = []

    missing_settings = [
        f"TG_{setting_name}"
        for setting_name in MANDATORY_SETTINGS
        if getattr(settings, setting_name) is None
    ]
    if missing_settings:
        problems.append(f"the following settings are missing: {', '.join(missing_settings)}")

    if settings.SMTP_SECURITY not in tuple(SMTPSecurity):
        problems.append(
            f"TG_SMTP_SECURITY is set to '{settings.SMTP_SECURITY}'."
            f" Accepted values: {', '.join(SMTPSecurity)}"
        )

    credentials = [getattr(settings, setting_name) for setting_name in CREDENTIAL_SETTINGS]
    if any(credentials) and not all(credentials):
        problems.append(
            "only one of TG_SMTP_USERNAME and TG_SMTP_PASSWORD is set. Set both to authenticate,"
            " or neither to send without authenticating"
        )

    return problems


def smtp_configured() -> bool:
    return not smtp_settings_problems()


class EmailTemplateException(Exception):
    pass


class BaseEmailTemplate:

    def __init__(self):
        compiler = Compiler()
        partials = {}

        def op_helper(op, _, *args):
            return getattr(operator, op)(*args)

        helpers = {
            op.replace("_", ""): functools.partial(op_helper, op)
            for op in (
                "eq", "ge", "gt", "le", "lt", "add", "sub", "and_", "or_", "contains",
            )
        }
        helpers["len"] = lambda _, *args: len(*args)

        for name, func in inspect.getmembers(self.__class__, predicate=callable):
            if (match := re.match(r"get_(\w+)_template", name)) and match.group(1) not in ("subject", "body"):
                partials[match.group(1)] = compiler.compile(func(self))
            if match := re.match(r"(\w+)_helper", name):
                helpers[match.group(1)] = func

        self.compiled_subject = functools.partial(
            compiler.compile(self.get_subject_template()), partials=partials, helpers=helpers,
        )
        self.compiled_body = functools.partial(
            compiler.compile(self.get_body_template()), partials=partials, helpers=helpers,
        )

    def validate_settings(self):
        if problems := smtp_settings_problems():
            for problem in problems:
                LOG.error(
                    "Template '%s' can not send emails because %s",
                    self.__class__.__name__,
                    problem,
                )

            raise EmailTemplateException("Invalid or insufficient email/SMTP settings")

        if settings.SMTP_USERNAME and settings.SMTP_SECURITY == SMTPSecurity.NONE:
            LOG.warning(
                "Template '%s' is configured to send SMTP credentials to %s:%s over an unencrypted"
                " connection.",
                self.__class__.__name__,
                settings.SMTP_ENDPOINT,
                settings.SMTP_PORT,
            )

    event_type: str = ""
    """Value of ``NotificationEvent`` this template renders for. Set by subclasses.
    Tags webhook payloads so a receiver can route by event.
    """

    def get_subject_template(self) -> str:
        raise NotImplementedError

    def get_body_template(self) -> str:
        raise NotImplementedError

    def webhook_summary(self, context: Mapping | None) -> str:
        """Rendered subject line with the ``[TestGen] `` prefix stripped.

        Reuses the compiled subject template so a receiver sees the same wording
        the matching email would carry, without prefix.
        """
        subject = self.compiled_subject(context or {}) or ""
        return subject.removeprefix("[TestGen] ")

    def webhook_data(self, context: Mapping | None) -> dict:  # noqa: ARG002
        """Plain-value event data for the webhook envelope's ``data`` field.

        Base returns ``{}``; subclasses override to expose event-specific facts.
        """
        return {}

    def webhook_project_name(self, context: Mapping | None) -> str | None:  # noqa: ARG002
        """Human-readable project name for the webhook envelope's ``project.name``.

        Base returns ``None``; each event subclass extracts the value from the
        shape its handler assembles (a nested summary attribute, a top-level key,
        etc.) so the envelope schema stays uniform across events.
        """
        return None

    def webhook_summary_url(self, context: Mapping | None) -> str | None:  # noqa: ARG002
        """Click-through URL for the webhook envelope's ``url`` field.

        Base returns ``None``; each event subclass returns the URL its email
        template uses as its "View on TestGen" link so a webhook receiver can
        offer the same navigation.
        """
        return None

    def get_message(self, recipients: list[str], context: Mapping | None) -> MIMEMultipart:
        subject = self.compiled_subject(context)
        body = self.compiled_body(context)

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["To"] = ", ".join(recipients)
        message["From"] = settings.EMAIL_FROM_ADDRESS
        message.attach(MIMEText(body, "html"))
        return message

    def connect(self) -> smtplib.SMTP:
        """Open the SMTP connection described by `TG_SMTP_SECURITY`."""
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)

        if settings.SMTP_SECURITY == SMTPSecurity.SSL:
            return smtplib.SMTP_SSL(
                settings.SMTP_ENDPOINT,
                settings.SMTP_PORT,
                context=ssl_context,
                timeout=SMTP_TIMEOUT_SECONDS,
            )

        smtp_server = smtplib.SMTP(settings.SMTP_ENDPOINT, settings.SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS)
        if settings.SMTP_SECURITY == SMTPSecurity.STARTTLS:
            try:
                smtp_server.starttls(context=ssl_context)
            except Exception:
                smtp_server.close()
                raise

        return smtp_server

    def describe_connection_failure(self, error: Exception) -> str:
        """Suggest the transport security the server appears to want, or return an empty string."""
        endpoint = f"{settings.SMTP_ENDPOINT}:{settings.SMTP_PORT}"

        if isinstance(error, ssl.SSLError) and settings.SMTP_SECURITY == SMTPSecurity.SSL:
            return (
                f" -- {endpoint} did not complete a TLS handshake."
                f" If it upgrades the connection instead, set TG_SMTP_SECURITY={SMTPSecurity.STARTTLS}."
            )

        if (
            isinstance(error, smtplib.SMTPServerDisconnected | smtplib.SMTPConnectError)
            and settings.SMTP_SECURITY != SMTPSecurity.SSL
        ):
            return (
                f" -- {endpoint} did not accept a plaintext connection."
                f" If it expects TLS from the first byte, set TG_SMTP_SECURITY={SMTPSecurity.SSL}."
            )

        if isinstance(error, smtplib.SMTPNotSupportedError):
            if "AUTH" in str(error):
                return (
                    f" -- {endpoint} offers no AUTH command. Clear TG_SMTP_USERNAME and TG_SMTP_PASSWORD"
                    " to send without authenticating, which is how a relay that authorizes by source"
                    " address or client certificate expects to be used."
                )

            if settings.SMTP_SECURITY == SMTPSecurity.STARTTLS:
                return (
                    f" -- {endpoint} does not offer STARTTLS. Use a port that does, or set"
                    f" TG_SMTP_SECURITY={SMTPSecurity.NONE} to send over an unencrypted connection."
                )

        return ""

    def send_mime_message(self, recipients: list[str], message: MIMEMultipart) -> dict:
        try:
            with self.connect() as smtp_server:
                if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                    smtp_server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                response = smtp_server.sendmail(settings.EMAIL_FROM_ADDRESS, recipients, message.as_string())
        except Exception as e:
            LOG.error( # noqa: TRY400
                "Template '%s' failed to send email with: %s%s",
                self.__class__.__name__,
                e,
                self.describe_connection_failure(e),
            )
            raise EmailTemplateException("Failed sending email notifications") from e
        else:
            return response

    def send(self, recipients: list[str], context: Mapping | None) -> dict:
        self.validate_settings()
        mime_message = self.get_message(recipients, context)
        response = self.send_mime_message(recipients, mime_message)

        LOG.info(
            "Template '%s' successfully sent email to %d recipients -- %d failed.",
            self.__class__.__name__,
            len(recipients) - len(response),
            len(response)
        )

        return response
