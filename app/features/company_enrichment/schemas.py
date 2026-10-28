from pydantic import BaseModel


class EnrichmentAck(BaseModel):
    """The 200 answer: the run was started, not finished."""

    received: bool = True
    boardId: str
    itemId: str


class EnrichmentRejected(BaseModel):
    error: str
