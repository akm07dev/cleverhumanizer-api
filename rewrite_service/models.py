from pydantic import BaseModel, Field


class RewriteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    html: str | None = None
    style: str = Field(default="casual", max_length=50)
    type_generation: str = Field(default="humanize", max_length=50)


class RewriteResponse(BaseModel):
    text: str
