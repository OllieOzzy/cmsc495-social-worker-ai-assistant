"""Validate requests and responses for generating and retrieving DAP drafts."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

# Trim surrounding whitespace before checking whether the text is empty.
NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class GenerateReportRequest(BaseModel):
    """Accept session notes for draft generation."""

    model_config = ConfigDict(extra="forbid")

    notes: Annotated[NonBlankText, StringConstraints(max_length=4000)]


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
