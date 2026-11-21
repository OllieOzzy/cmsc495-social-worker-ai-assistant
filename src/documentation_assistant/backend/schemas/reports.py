"""Define the request, response, and model output schemas for DAP reports."""

from datetime import date, datetime, time
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

# Trim surrounding whitespace before checking whether the text is empty.
NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SessionNotes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
RequiredSessionNotes = Annotated[SessionNotes, StringConstraints(min_length=1)]
MetadataText = Annotated[NonBlankText, StringConstraints(max_length=200)]
ReportingText = Annotated[NonBlankText, StringConstraints(max_length=1000)]
ReportStatus = Literal["draft", "approved"]
ReportRevision = Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]
YesNo = Literal["yes", "no"]


class InvalidSessionTimeRange(ValueError):
    """The end time precedes the start time on a same-day report."""


class ReportMetadata(BaseModel):
    """Hold optional session details and the workflow's draft source."""

    model_config = ConfigDict(extra="forbid")

    student_name: MetadataText | None = None
    student_id: MetadataText | None = None
    school: MetadataText | None = None
    grade: MetadataText | None = None
    date_of_service: date | None = None
    social_worker_name: MetadataText | None = None
    service_basis: Literal["iep", "504", "general_referral"] | None = None
    start_time: time | None = Field(
        default=None,
        description="Local start time in HH:MM format.",
        examples=["09:00"],
        json_schema_extra={"example": "09:00"},
    )
    end_time: time | None = Field(
        default=None,
        description="Local end time in HH:MM format.",
        examples=["09:25"],
        json_schema_extra={"example": "09:25"},
    )
    session_type: Literal["individual", "group", "family"] | None = None
    setting: Literal["in_person", "virtual"] | None = None
    iep_504_goal_addressed: MetadataText | None = None
    social_worker_credential: MetadataText | None = None
    safety_concern: YesNo | None = None
    safety_concern_description: MetadataText | None = None
    mandated_report_details: ReportingText | None = None
    supervisor_notification: ReportingText | None = None
    draft_source: Literal["handwritten", "ai_assisted"] | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_session_time(cls, value: time | None) -> time | None:
        """Accept local times with no timezone or nonzero seconds."""
        if value is not None and (
            value.tzinfo is not None or value.second or value.microsecond
        ):
            raise ValueError("Use a local time in HH:MM format")
        return value

    def validate_time_range(self, saved: "ReportMetadata | None" = None) -> None:
        """Reject an end time before the start time after applying any edits."""
        start = self.start_time
        end = self.end_time
        if saved is not None:
            # Omitted fields keep saved times. An explicit null clears a time.
            if "start_time" not in self.model_fields_set:
                start = saved.start_time
            if "end_time" not in self.model_fields_set:
                end = saved.end_time
        if start is not None and end is not None and end < start:
            raise InvalidSessionTimeRange("End time must be at or after start time.")


class SavedReportMetadata(ReportMetadata):
    """Include the calculated duration in saved report responses."""

    @computed_field
    @property
    def total_minutes(self) -> int | None:
        """Return minutes for a valid same-day range, or None otherwise."""
        if self.start_time is None or self.end_time is None:
            return None
        start = self.start_time.hour * 60 + self.start_time.minute
        end = self.end_time.hour * 60 + self.end_time.minute
        return end - start if end >= start else None


class ReportFilters(BaseModel):
    """Validate report search fields, service dates, and pagination bounds."""

    model_config = ConfigDict(extra="forbid")

    student_name: MetadataText | None = None
    student_id: MetadataText | None = None
    school: MetadataText | None = None
    grade: MetadataText | None = None
    date_from: date | None = None
    date_to: date | None = None
    social_worker_name: MetadataText | None = None

    status: ReportStatus | None = None
    approved_by: MetadataText | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 25
    offset: Annotated[int, Field(ge=0, le=2**63 - 1)] = 0

    # Compare the two dates after Pydantic has parsed both filter fields.
    @model_validator(mode="after")
    def validate_date_range(self) -> "ReportFilters":
        """Reject a reversed service date range when both bounds are supplied."""
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class GenerateReportRequest(BaseModel):
    """Require session notes for an AI-assisted draft."""

    model_config = ConfigDict(extra="forbid")

    notes: RequiredSessionNotes
    metadata: ReportMetadata | None = None


class ManualReportRequest(BaseModel):
    """Accept optional notes and details for a handwritten draft."""

    model_config = ConfigDict(extra="forbid")

    notes: SessionNotes = ""
    metadata: ReportMetadata | None = None


class DraftSections(BaseModel):
    """Allow blank text in any section while a report is being drafted."""

    model_config = ConfigDict(extra="forbid")

    data: Annotated[str, StringConstraints(strip_whitespace=True)]
    assessment: Annotated[str, StringConstraints(strip_whitespace=True)]
    plan: Annotated[str, StringConstraints(strip_whitespace=True)]


class DAPSections(DraftSections):
    """Require nonblank Data, Assessment, and Plan in the model output."""

    data: NonBlankText
    assessment: NonBlankText
    plan: NonBlankText


class ReportContent(BaseModel):
    """Identify a report and carry its DAP sections."""

    report_id: UUID
    sections: DraftSections


class ReportDraft(ReportContent):
    """Return the ID, status, and sections of a newly generated draft."""

    status: Literal["draft"] = "draft"
    sections: DAPSections


class StoredReportDraft(ReportContent):
    """Return a saved report with its source notes, metadata, and review state."""

    owner_id: UUID | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True)]
    metadata: SavedReportMetadata | None = None
    status: ReportStatus = "draft"
    revision: ReportRevision = 1
    approved_at: datetime | None = None
    approved_by: MetadataText | None = None


class ReportRevisionRequest(BaseModel):
    """Identify the saved revision for a review action."""

    model_config = ConfigDict(extra="forbid")

    revision: ReportRevision


class ApproveReportRequest(ReportRevisionRequest):
    """Record who explicitly approves the saved revision."""

    approved_by: MetadataText


class DraftUpdateRequest(ReportRevisionRequest):
    """Identify a draft revision and validate optional metadata edits."""

    metadata: ReportMetadata | None = None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: ReportMetadata | None) -> ReportMetadata | None:
        """Reject draft_source in edits, including an explicit null."""
        if value is not None and "draft_source" in value.model_fields_set:
            raise ValueError("Draft source is managed by the report workflow")
        return value


class EditReportRequest(DraftUpdateRequest):
    """Update source notes, DAP sections, or report metadata on a saved draft."""

    notes: SessionNotes | None = None
    sections: DraftSections | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> "EditReportRequest":
        """Require notes, replacement sections, or at least one metadata key."""
        if (
            self.notes is None
            and self.sections is None
            and (self.metadata is None or not self.metadata.model_fields_set)
        ):
            raise ValueError("Provide notes, sections, or a metadata field to update")
        return self


class RegenerateReportRequest(DraftUpdateRequest):
    """Require source notes and the current revision for AI regeneration."""

    notes: RequiredSessionNotes


class ReportSummary(BaseModel):
    """Provide identifying details and review status for the report list."""

    report_id: UUID
    owner_id: UUID | None = None
    status: ReportStatus = "draft"
    created_at: datetime | None
    metadata: SavedReportMetadata | None = None
    approved_by: MetadataText | None = None
