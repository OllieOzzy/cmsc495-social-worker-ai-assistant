"""Validate requests and responses for generating and retrieving DAP drafts."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

# Trim surrounding whitespace before checking whether the text is empty.
NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
MetadataText = Annotated[NonBlankText, StringConstraints(max_length=200)]


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


class ReportDraft(BaseModel):
    """Return the draft ID and generated sections after saving the draft."""

    report_id: UUID
    status: Literal["draft"] = "draft"
    sections: DAPSections


class StoredReportDraft(ReportDraft):
    """Include the submitted notes for side-by-side review of a saved draft."""

    notes: NonBlankText
    metadata: ReportMetadata | None = None


class ReportSummary(BaseModel):
    """Identify a saved draft and include its timestamp when available."""

    report_id: UUID
    status: Literal["draft"] = "draft"
    created_at: datetime | None
    metadata: ReportMetadata | None = None
