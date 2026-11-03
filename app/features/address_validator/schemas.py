from __future__ import annotations

from pydantic import BaseModel, Field


class BlockOutput(BaseModel):
    """A successful run: the blocks declare no output fields."""

    outputFields: dict = Field(default_factory=dict)


class MondayError(BaseModel):
    """monday's error format (app/core/blocks.py::monday_error)."""

    severityCode: int
    notificationErrorTitle: str
    notificationErrorDescription: str
    runtimeErrorDescription: str
