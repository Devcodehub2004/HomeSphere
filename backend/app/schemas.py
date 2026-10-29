from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


from pydantic import BaseModel, ConfigDict, Field, field_validator

class HomeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)

    @field_validator("name", "city")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be empty")
        return value

class HomeRead(HomeCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime