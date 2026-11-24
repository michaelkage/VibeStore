from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class HealthResponse(BaseModel):
    status: str
    service: str
    database: str
    redis: str


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


class SDKDetection(BaseModel):
    name: str
    category: str
    file_path: str
    line_number: int
    evidence: str
    confidence: str
    explanation: str


class StaticManifestFinding(BaseModel):
    category: str
    severity: str
    title: str
    file_path: str
    line_number: int
    evidence: str
    explanation: str


class InspectionResponse(BaseModel):
    repository: str
    manifest_found: bool
    package_name: str | None = None
    permissions: list[ManifestFinding]
    sdk_detections: list[SDKDetection] = Field(default_factory=list)
    manifest_warnings: list[StaticManifestFinding] = Field(default_factory=list)
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


class IndexRepositoryResponse(BaseModel):
    id: str
    name: str
    repository_url: str
    default_branch: str
    latest_commit_sha: str
    stars: int
    indexed_files: int



class RepositorySubmissionResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    repository_url: str
    default_branch: str
    latest_commit_sha: str | None = None
    stars: int
    submitted_at: datetime
    indexed_at: datetime | None = None


class RepositoryIndexJobResponse(BaseModel):
    id: str
    status: str
    repository_url: str
    attempt_count: int
    error: str | None = None
    app_id: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

class RemixSessionCreateRequest(BaseModel):
    app_id: UUID
    title: str = Field(default="New remix", min_length=1, max_length=120)


class RemixMessageCreateRequest(BaseModel):
    content: str = Field(min_length=3, max_length=4_000)


class RemixMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    message_type: str
    evidence: list[dict] = Field(default_factory=list)
    created_at: datetime


class RemixSessionResponse(BaseModel):
    id: str
    app_id: str
    app_name: str
    repository_url: str
    source_commit_sha: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: list[RemixMessageResponse] = Field(default_factory=list)


class RemixPatchProposalCreateRequest(BaseModel):
    content: str = Field(min_length=3, max_length=4_000)


class RemixPatchProposalReviewRequest(BaseModel):
    decision: str = Field(pattern=r"^(approved|rejected)$")


class RemixPatchProposalResponse(BaseModel):
    id: str
    session_id: str
    base_commit_sha: str
    status: str
    summary: str
    proposal: dict
    source_files: list[dict]
    validation_status: str
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
