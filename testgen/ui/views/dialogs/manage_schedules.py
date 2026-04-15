from typing import Any

import cron_converter
import cron_descriptor
import streamlit as st
from sqlalchemy.exc import IntegrityError

from testgen.common.models import Session, with_database_session
from testgen.common.models.scheduler import JobSchedule
from testgen.ui.session import session

CRON_SAMPLE_COUNT = 3
RESULT_KEY = "schedule_dialog:result"
CRON_SAMPLE_KEY = "schedule_dialog:cron_sample"


class ScheduleDialog:

    title: str = ""
    arg_label: str = ""
    job_key: str = ""

    def __init__(self, project_code: str = ""):
        self.project_code = project_code

    def init(self) -> None:
        raise NotImplementedError

    def get_arg_value(self, job):
        raise NotImplementedError

    def get_arg_value_options(self) -> list[dict[str, str]]:
        raise NotImplementedError

    def get_job_arguments(self, arg_value: str) -> tuple[list[Any], dict[str, Any]]:
        raise NotImplementedError

    def build_data(self) -> dict:
        self.init()
        user_can_edit = session.auth.user_has_permission("edit")

        with Session() as db_session:
            scheduled_jobs = (
                db_session.query(JobSchedule)
                .where(JobSchedule.project_code == self.project_code, JobSchedule.key == self.job_key)
            )
            scheduled_jobs_json = [
                {
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
                for job in scheduled_jobs
            ]

        return {
            "title": self.title,
            "items": scheduled_jobs_json,
            "arg_label": self.arg_label,
            "arg_values": self.get_arg_value_options(),
            "permissions": {"can_edit": user_can_edit},
            "sample": st.session_state.get(CRON_SAMPLE_KEY),
            "results": st.session_state.get(RESULT_KEY),
        }

    def on_delete(self, item: dict) -> None:
        with_database_session(lambda: JobSchedule.delete(item["id"]))()
        st.session_state.pop(RESULT_KEY, None)

    def on_pause(self, item: dict) -> None:
        with_database_session(lambda: JobSchedule.update_active(item["id"], False))()
        st.session_state.pop(RESULT_KEY, None)

    def on_resume(self, item: dict) -> None:
        with_database_session(lambda: JobSchedule.update_active(item["id"], True))()
        st.session_state.pop(RESULT_KEY, None)

    def on_cron_sample(self, payload: dict) -> None:
        from testgen.ui.utils import get_cron_sample
        sample = get_cron_sample(payload["cron_expr"], payload["tz"], CRON_SAMPLE_COUNT, formatted=True)
        st.session_state[CRON_SAMPLE_KEY] = sample

    def on_add(self, payload: dict) -> None:
        arg_value = payload.get("arg_value")
        cron_expr = payload.get("cron_expr")
        cron_tz = payload.get("cron_tz")
        try:
            is_form_valid = bool(arg_value) and bool(cron_tz) and bool(cron_expr)
            if is_form_valid:
                cron_obj = cron_converter.Cron(cron_expr)
                args, kwargs = self.get_job_arguments(arg_value)
                sched_model = JobSchedule(
                    project_code=self.project_code,
                    key=self.job_key,
                    cron_expr=cron_obj.to_string(),
                    cron_tz=cron_tz,
                    active=True,
                    args=args,
                    kwargs=kwargs,
                )
                with_database_session(sched_model.save)()
                st.session_state[RESULT_KEY] = {"success": True, "message": "Schedule added"}
            else:
                st.session_state[RESULT_KEY] = {"success": False, "message": "Complete all the fields before adding the schedule"}
        except IntegrityError:
            st.session_state[RESULT_KEY] = {"success": False, "message": "This schedule already exists."}
        except ValueError as e:
            st.session_state[RESULT_KEY] = {"success": False, "message": str(e)}
        except Exception:
            st.session_state[RESULT_KEY] = {"success": False, "message": "Error validating the Cron expression"}

    def clear_state(self) -> None:
        st.session_state.pop(RESULT_KEY, None)
        st.session_state.pop(CRON_SAMPLE_KEY, None)
