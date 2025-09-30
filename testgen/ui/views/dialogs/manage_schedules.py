import json
import zoneinfo
from datetime import datetime
from typing import Any

import cron_converter
import cron_descriptor
import streamlit as st
from sqlalchemy.exc import IntegrityError

from testgen.common.models import Session, with_database_session
from testgen.common.models.scheduler import JobSchedule
from testgen.ui.components import widgets as testgen
from testgen.ui.session import session, temp_value

CRON_SAMPLE_COUNT = 3
class ScheduleDialog:

    title: str = ""
    arg_label: str = ""
    job_key: str = ""

    def __init__(self):
        self.project_code = None

    def init(self) -> None:
        raise NotImplementedError

    def get_arg_value(self, job):
        raise NotImplementedError

    def get_arg_value_options(self) -> list[dict[str, str]]:
        raise NotImplementedError

    def get_job_arguments(self, arg_value: str) -> tuple[list[Any], dict[str, Any]]:
        raise NotImplementedError

    @with_database_session
    def open(self, project_code: str) -> None:
        self.project_code = project_code
        self.init()
        return st.dialog(title=self.title)(self.render)()

    def render(self) -> None:
        @with_database_session
        def on_delete_sched(item):
            JobSchedule.delete(item["id"])
            st.rerun(scope="fragment")

        @with_database_session
        def on_pause_sched(item):
            JobSchedule.update_active(item["id"], False)
            st.rerun(scope="fragment")

        @with_database_session
        def on_resume_sched(item):
            JobSchedule.update_active(item["id"], True)
            st.rerun(scope="fragment")

        def on_cron_sample(payload: dict[str, str]):
            try:
                cron_expr = payload["cron_expr"]
                cron_tz = payload.get("tz", "America/New_York")

                cron_obj = cron_converter.Cron(cron_expr)
                cron_schedule = cron_obj.schedule(datetime.now(zoneinfo.ZoneInfo(cron_tz)))
                readble_cron_schedule = cron_descriptor.get_description(
                    cron_expr,
                )

                set_cron_sample({
                    "samples": [cron_schedule.next().strftime("%a %b %-d, %-I:%M %p") for _ in range(CRON_SAMPLE_COUNT)],
                    "readable_expr": readble_cron_schedule,
                })
            except ValueError as e:
                set_cron_sample({"error": str(e)})
            except Exception as e:
                set_cron_sample({"error": "Error validating the Cron expression"})

        def on_add_schedule(payload: dict[str, str]):
            set_arg_value(payload["arg_value"])
            set_timezone(payload["cron_tz"])
            set_cron_expr(payload["cron_expr"])

            set_should_save(True)

        user_can_edit = session.auth.user_has_permission("edit")
        cron_sample_result, set_cron_sample = temp_value("schedule_dialog:cron_expr_validation", default={})
        get_arg_value, set_arg_value = temp_value("schedule_dialog:new:arg_value", default=None)
        get_timezone, set_timezone = temp_value("schedule_dialog:new:timezone", default=None)
        get_cron_expr, set_cron_expr = temp_value("schedule_dialog:new:cron_expr", default=None)
        should_save, set_should_save = temp_value("schedule_dialog:new:should_save", default=False)

        results = None
        if should_save():
            success = True
            message = "Schedule added"

            try:
                arg_value = get_arg_value()
                cron_expr = get_cron_expr()
                cron_tz = get_timezone()

                is_form_valid = (
                    bool(arg_value)
                    and bool(cron_tz)
                    and bool(cron_expr)
                )

                if is_form_valid:
                    cron_obj = cron_converter.Cron(cron_expr)
                    args, kwargs = self.get_job_arguments(arg_value)
                    with Session() as db_session:
                        sched_model = JobSchedule(
                            project_code=self.project_code,
                            key=self.job_key,
                            cron_expr=cron_obj.to_string(),
                            cron_tz=cron_tz,
                            active=True,
                            args=args,
                            kwargs=kwargs,
                        )
                        db_session.add(sched_model)
                        db_session.commit()
                else:
                    success = False
                    message = "Complete all the fields before adding the schedule"
            except IntegrityError:
                success = False
                message = "This schedule already exists."
            except ValueError as e:
                success = False
                message = str(e)
            except Exception as e:
                success = False
                message = "Error validating the Cron expression"
            results = {"success": success, "message": message}

        with Session() as db_session:
            scheduled_jobs = (
                db_session.query(JobSchedule)
                .where(JobSchedule.project_code == self.project_code, JobSchedule.key == self.job_key)
            )
            scheduled_jobs_json = []
            for job in scheduled_jobs:
                job_json = {
                    "id": str(job.id),
                    "argValue": self.get_arg_value(job),
                    "cronExpr": job.cron_expr,
                    "readableExpr": cron_descriptor.get_description(job.cron_expr),
                    "cronTz": job.cron_tz_str,
                    "sample": [
                        sample.strftime("%a %b %-d, %-I:%M %p")
                        for sample in job.get_sample_triggering_timestamps(CRON_SAMPLE_COUNT + 1)
                    ],
                    "active": job.active,
                }
                scheduled_jobs_json.append(job_json)

        testgen.css_class("l-dialog")
        testgen.testgen_component(
            "schedule_list",
            props={
                "items": json.dumps(scheduled_jobs_json),
                "arg_label": self.arg_label,
                "arg_values": self.get_arg_value_options(),
                "permissions": {"can_edit": user_can_edit},
                "sample": cron_sample_result(),
                "results": results,
            },
            event_handlers={
                "PauseSchedule": on_pause_sched,
                "ResumeSchedule": on_resume_sched,
                "DeleteSchedule": on_delete_sched,
            },
            on_change_handlers={
                "GetCronSample": on_cron_sample,
                "AddSchedule": on_add_schedule,
            },
        )
