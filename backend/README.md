# VibeStore API

FastAPI service for VibeStore discovery and repository intelligence. The service is separate from the existing Flutter app and preserves its app-source and installation pipeline.

## Local development

Requirements: Docker Compose and Python 3.11+ (Python is needed only for local tests outside Docker).

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
``

Put the generated value in `JWT_SECRET_KEY` in `.env`, then start the services:

```bash
docker compose up --build -d
docker compose exec -T db psql -U vibestore -d vibestore < migrations/001_initial.sql
docker compose exec -T db psql -U vibestore -d vibestore < migrations/002_authentication.sql
docker compose exec -T db psql -U vibestore -d vibestore < migrations/003_repository_submissions.sql
``

OpenAPI: http://localhost:8000/docs  
Health: http://localhost:8000/health

## API

- `GET /health`: database-aware service health.
- `POST /api/v1/auth/register`: create an account and issue a short-lived access token.
- `POST /api/v1/auth/token`: exchange email/password for an access token.
- `GET /api/v1/auth/me`: return the authenticated account.
- `POST /api/v1/repositories/index`: authenticated GitHub repository indexing with bounded README/manifest retrieval and catalog persistence. Apply migration `003_repository_submissions.sql` first.
- `POST /api/v1/search`: PostgreSQL full-text app catalog search.
- `POST /api/v1/repositories/inspect`: fetch a public GitHub repository's Android manifest and report declared permissions.

Example registration:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"developer@example.com","password":"use-a-long-unique-password"}'
```

Use the returned `access_token` as `Authorization: Bearer <token>` for `/auth/me`.

## Authentication security

- Passwords are hashed with Argon2 through pwdlib; plaintext passwords are never stored.
- Access tokens are signed HS256 JWTs with issuer, issue time and expiry claims.
- `JWT_SECRET_KEY` must be a unique random value of at least 32 characters. Never commit it.
- Account email addresses are normalized to lowercase and protected by a unique database index.
- Login failures use a generic error response.
- Access tokens are short-lived; refresh-token rotation, email verification, password reset, account recovery, MFA, and authentication rate limiting are not yet implemented. Do not expose this service to the public internet as a production identity provider until these controls are added.

## AI provider adapter

A provider-neutral `AIProvider` interface and OpenAI-compatible adapter are included. Configure `AI_PROVIDER=openai-compatible`, `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, and optionally `AI_EMBEDDING_MODEL`. Use `AI_PROVIDER=none` to disable model calls. AI calls are not yet connected to user-facing workflows.

## Repository inspection limits

Repository files are fetched as data and never executed. The indexing endpoint accepts canonical GitHub repository URLs only, rejects truncated repository trees, caps retrieval to 12 candidate files and 1 MB per file, and stores bounded text excerpts. Current analysis checks Android manifest permission declarations only. A declared permission does not prove runtime use. Private GitHub repository support requires a configured token with the appropriate repository permissions. GitLab/Codeberg integrations, tracker detection, architecture analysis and evidence-backed AI reports are not implemented yet.

## Remaining platform work

The initial schema enables pgvector and records catalog, repository file, inspection and remix-job metadata. Automated catalog ingestion, embeddings and vector ranking, background queue consumers, GitHub webhook signature verification, comprehensive X-Ray analysis, remix agent/orchestration, isolated Gradle workers, isolated APK signing, artifact storage/delivery, notifications and Flutter discovery/X-Ray/Remix screens remain outstanding. The remix table is groundwork only: no arbitrary repository code is built or signed by this API.

Production deployments must replace Compose credentials, use TLS, restrict CORS, protect secrets, verify webhook signatures, configure backup/restore, add observability, and keep builds in disposable network-restricted sandboxes. Signing keys must remain outside both the API and build workers.
