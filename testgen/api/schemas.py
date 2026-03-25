"""Pydantic request/response models for API v1 endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# --- Requests ---


class SubmitProfilingRequest(BaseModel):
    table_group_id: UUID


class SubmitTestRunRequest(BaseModel):
    test_suite_id: UUID


class SubmitTestGenerationRequest(BaseModel):
    test_suite_id: UUID


# --- Responses ---


class JobSubmittedResponse(BaseModel):
    """Returned on 202 Accepted after successful job submission."""

    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class JobResponse(BaseModel):
    """Full job execution record returned by status and cancel endpoints."""

    id: UUID
    job_key: str
    status: str
    source: str
    created_at: datetime
    claimed_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


# --- Errors ---


class ErrorDetail(BaseModel):
    """A single error entry."""

    code: str
    detail: str


class ErrorResponse(BaseModel):
    """Standardized error response for business logic errors (400, 404, 409)."""

    errors: list[ErrorDetail]
