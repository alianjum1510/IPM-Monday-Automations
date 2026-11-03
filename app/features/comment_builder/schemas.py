"""What the Comment Builder page sends and gets back (for the OpenAPI docs; the routes read the body themselves)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WriteRequest(BaseModel):
    prompt: str


class SummarizeRequest(BaseModel):
    text: str


class AutofillRequest(BaseModel):
    comment: str
    options: dict = Field(default_factory=dict, description="allowed values per field, from the comment form")
    examples: list = Field(default_factory=list, description="earlier comments on the same deal")
    today: str = ""
    weekday: str = ""
    dealName: str = ""
    dealStage: str = ""


class TextResponse(BaseModel):
    text: str


class AutofillResponse(BaseModel):
    fields: dict


class FileResponse(BaseModel):
    """The asset monday made: `url` is monday's link to the file (opens / downloads it for a logged-in user)."""

    id: str
    name: str
    url: str


class ViewErrorResponse(BaseModel):
    """app/core/views.py: the page shows `error`."""

    error: str
