"""Validate requests and responses for generating and retrieving DAP drafts."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# Trim surrounding whitespace before checking whether the text is empty.
NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
MetadataText = Annotated[NonBlankText, StringConstraints(max_length=200)]
ReportStatus = Literal["draft", "approved"]
ReportRevision = Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]


class ReportMetadata(BaseModel):
    """Capture optional report details entered by the reviewer."""

    model_config = ConfigDict(extra="forbid")

    student_name: MetadataText | None = None
    student_id: MetadataText | None = None
    school: MetadataText | None = None
    grade: MetadataText | None = None
    date_of_service: date | None = None
    social_worker_name: MetadataText | None = None


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
    """Accept session notes for draft generation."""

    model_config = ConfigDict(extra="forbid")

    notes: Annotated[NonBlankText, StringConstraints(max_length=4000)]
    metadata: ReportMetadata | None = None


class DAPSections(BaseModel):
    """Require Data, Assessment, and Plan text in the model output."""

    model_config = ConfigDict(extra="forbid")

    data: NonBlankText
    assessment: NonBlankText
    plan: NonBlankText


class ReportContent(BaseModel):
    """Identify a report and carry its DAP sections."""

    report_id: UUID
    sections: DAPSections


class ReportDraft(ReportContent):
    """Return a newly generated draft."""

    status: Literal["draft"] = "draft"


class StoredReportDraft(ReportContent):
    """Return the saved report, source notes, and review state."""

    notes: NonBlankText
    metadata: ReportMetadata | None = None
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


class EditReportRequest(ReportRevisionRequest):
    """Update DAP sections, report metadata, or both on a saved draft."""

    sections: DAPSections | None = None
    metadata: ReportMetadata | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> "EditReportRequest":
        """Require sections or at least one explicitly supplied metadata field."""
        if self.sections is None and (
            self.metadata is None or not self.metadata.model_fields_set
        ):
            raise ValueError(
                "Provide sections or at least one metadata field to update"
            )
        return self


class ReportSummary(BaseModel):
    """Identify a saved report and include its current review status."""

    report_id: UUID
    status: ReportStatus = "draft"
    created_at: datetime | None
    metadata: ReportMetadata | None = None
    approved_by: MetadataText | None = None
