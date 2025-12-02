from unittest.mock import ANY, call, patch

import pytest

from testgen.common.email import BaseEmailTemplate, EmailTemplateException


class TestEmailTemplate(BaseEmailTemplate):

    def get_subject_template(self) -> str:
        return "{{project}}: Test execution finished"

    def get_body_template(self) -> str:
        return "<html><body><h1>DataKitchen TestGen</h1><p>Hi, {{user}}!</p></body></html>"


@pytest.fixture
def smtp_mock():
    with patch("testgen.common.email.smtplib.SMTP_SSL") as mock:
        yield mock


@pytest.fixture
def def_settings():
    with patch("testgen.common.email.settings") as mock:
        mock.EMAIL_FROM_ADDRESS = "from@email"
        mock.SMTP_ENDPOINT = "smtp-endpoint"
        mock.SMTP_PORT = 333
        mock.SMTP_USERNAME = "smtp-user"
        mock.SMTP_PASSWORD = "smtp-pass"  # noqa: S105
        yield mock


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
            call("smtp-endpoint", 333, context=ANY),
            call().__enter__().login("smtp-user", "smtp-pass"),
            call().__enter__().sendmail("from@email", ["test@data.kitchen"], ANY)
        ],
        any_order=True,
    )
    email_body = smtp_mock().__enter__().sendmail.call_args_list[0][0][2]
    assert "<h1>DataKitchen TestGen</h1>" in email_body
    assert "Subject: Test Project: Test execution finished" in email_body
    assert "<p>Hi, Test user!</p>" in email_body


@pytest.mark.parametrize(
    "missing",
    ("EMAIL_FROM_ADDRESS", "SMTP_ENDPOINT", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD")
)
def test_settings_validation(missing, template, def_settings, send_args):
    setattr(def_settings, missing, None)
    with pytest.raises(EmailTemplateException, match="Invalid or insufficient email/SMTP settings"):
        template.send(*send_args)
