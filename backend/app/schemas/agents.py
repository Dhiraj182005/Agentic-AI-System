from pydantic import BaseModel, Field, field_validator


class AgentTestRequest(BaseModel):
    agent: str = Field(min_length=1, max_length=50)
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("agent", "message")
    @classmethod
    def _strip_and_reject_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be empty or whitespace only")
        return value


class AgentTestResponse(BaseModel):
    agent: str
    role: str
    response: str
    provider: str
    model: str