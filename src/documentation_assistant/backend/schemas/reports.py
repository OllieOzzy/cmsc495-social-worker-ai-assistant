"""Validate requests and responses for generating and retrieving DAP drafts."""

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
    """Capture optional report details entered by the reviewer."""

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
        """Accept local clock times at minute precision."""
        if value is not None and (
            value.tzinfo is not None or value.second or value.microsecond
        ):
            raise ValueError("Use a local time in HH:MM format")
        return value

    def validate_time_range(self, saved: "ReportMetadata | None" = None) -> None:
        """Check the times after applying any supplied fields to the saved values."""
        start = self.start_time
        end = self.end_time
        if saved is not None:
            if "start_time" not in self.model_fields_set:
                start = saved.start_time
            if "end_time" not in self.model_fields_set:
                end = saved.end_time
        if start is not None and end is not None and end < start:
            raise InvalidSessionTimeRange("End time must be at or after start time.")


class SavedReportMetadata(ReportMetadata):
    """Return saved details with the duration derived from the session times."""

    @computed_field
    @property
    def total_minutes(self) -> int | None:
        """Return the duration when both times form a valid same-day range."""
        if self.start_time is None or self.end_time is None:
            return None
        start = self.start_time.hour * 60 + self.start_time.minute
        end = self.end_time.hour * 60 + self.end_time.minute
        return end - start if end >= start else None


class ReportFilters(BaseModel):
    """Validate optional report search fields and service date bounds."""

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

    # Compare the two dates after Pydantic has parsed both filter fields.
    @model_validator(mode="after")
    def validate_date_range(self) -> "ReportFilters":
        """Require the start date to be on or before the end date."""
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
    """Accept editable DAP sections, including sections still blank."""

    model_config = ConfigDict(extra="forbid")

    data: Annotated[str, StringConstraints(strip_whitespace=True)]
    assessment: Annotated[str, StringConstraints(strip_whitespace=True)]
    plan: Annotated[str, StringConstraints(strip_whitespace=True)]


class DAPSections(DraftSections):
    """Require Data, Assessment, and Plan text in the model output."""

    data: NonBlankText
    assessment: NonBlankText
    plan: NonBlankText


class ReportContent(BaseModel):
    """Identify a report and carry its DAP sections."""

    report_id: UUID
    sections: DraftSections


class ReportDraft(ReportContent):
    """Return a newly generated draft."""

    status: Literal["draft"] = "draft"
    sections: DAPSections


class StoredReportDraft(ReportContent):
    """Return the saved report, source notes, and review state."""

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
        """Reserve draft source changes for the generation workflow."""
        if value is not None and "draft_source" in value.model_fields_set:
            raise ValueError("Draft source is managed by the report workflow")
        return value


class EditReportRequest(DraftUpdateRequest):
    """Update source notes, DAP sections, or report metadata on a saved draft."""

    notes: SessionNotes | None = None
    sections: DraftSections | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> "EditReportRequest":
        """Require at least one field to update."""
        if (
            self.notes is None
            and self.sections is None
            and (self.metadata is None or not self.metadata.model_fields_set)
        ):
            raise ValueError("Provide notes, sections, or a metadata field to update")
        return self


class RegenerateReportRequest(DraftUpdateRequest):
    """Generate replacement DAP sections from corrected source notes."""

    notes: RequiredSessionNotes


class ReportSummary(BaseModel):
    """Identify a saved report and include its current review status."""

    report_id: UUID
    status: ReportStatus = "draft"
    created_at: datetime | None
    metadata: SavedReportMetadata | None = None
    approved_by: MetadataText | None = None
