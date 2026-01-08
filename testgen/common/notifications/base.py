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

LOG = logging.getLogger(__name__)

MANDATORY_SETTINGS = (
    "EMAIL_FROM_ADDRESS",
    "SMTP_ENDPOINT",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
)


def smtp_configured() -> bool:
    return all(getattr(settings, setting_name) is not None for setting_name in MANDATORY_SETTINGS)


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
        missing_settings = [
            f"TG_{setting_name}"
            for setting_name in MANDATORY_SETTINGS
            if getattr(settings, setting_name) is None
        ]

        if missing_settings:
            LOG.error(
                "Template '%s' can not send emails because the following settings are missing: %s",
                self.__class__.__name__,
                ", ".join(missing_settings),
            )

            raise EmailTemplateException("Invalid or insufficient email/SMTP settings")

    def get_subject_template(self) -> str:
        raise NotImplementedError

    def get_body_template(self) -> str:
        raise NotImplementedError

    def get_message(self, recipients: list[str], context: Mapping | None) -> MIMEMultipart:
        subject = self.compiled_subject(context)
        body = self.compiled_body(context)

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["To"] = ", ".join(recipients)
        message["From"] = settings.EMAIL_FROM_ADDRESS
        message.attach(MIMEText(body, "html"))
        return message

    def send_mime_message(self, recipients: list[str], message: MIMEMultipart) -> dict:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        try:
            with smtplib.SMTP_SSL(settings.SMTP_ENDPOINT, settings.SMTP_PORT, context=ssl_context) as smtp_server:
                smtp_server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                response = smtp_server.sendmail(settings.EMAIL_FROM_ADDRESS, recipients, message.as_string())
        except Exception as e:
            LOG.error("Template '%s' failed to send email with: %s", self.__class__.__name__, e) # noqa: TRY400
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
