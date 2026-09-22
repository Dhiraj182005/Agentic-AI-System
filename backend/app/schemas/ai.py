from pydantic import BaseModel, Field


class AITestRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class AITestResponse(BaseModel):
    response: str
    provider: str
    model: str