"""Contracts for generating an unapproved DAP draft."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class GenerateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: Annotated[NonBlankText, StringConstraints(max_length=4000)]


class DAPSections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: NonBlankText
    assessment: NonBlankText
    plan: NonBlankText


class ReportDraft(BaseModel):
    status: Literal["draft"] = "draft"
    sections: DAPSections
