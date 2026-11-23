from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class HealthResponse(BaseModel):
    status: str
    service: str
    database: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    limit: int = Field(default=20, ge=1, le=50)


class SearchResult(BaseModel):
    id: str
    name: str
    description: str | None = None
    repository_url: str
    score: float


class RepositoryRequest(BaseModel):
    repository_url: HttpUrl


class ManifestFinding(BaseModel):
    permission: str
    risk: str
    explanation: str


class InspectionResponse(BaseModel):
    repository: str
    manifest_found: bool
    package_name: str | None = None
    permissions: list[ManifestFinding]
    limitations: list[str]


class RegisterRequest(BaseModel):
    email: str = Field(min_length=6, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=6, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
