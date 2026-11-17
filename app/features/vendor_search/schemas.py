from pydantic import BaseModel, Field


class BlockOutput(BaseModel):
    """The run was started (not finished): the block declares no output fields."""

    outputFields: dict = Field(default_factory=dict)


class MondayError(BaseModel):
    """monday's error format (app/core/blocks.py::monday_error)."""

    severityCode: int
    notificationErrorTitle: str
    notificationErrorDescription: str
    runtimeErrorDescription: str
