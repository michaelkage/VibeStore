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
docker compose exec -T db psql -U vibestore -d vibestore < migrations/004_semantic_embeddings.sql
docker compose exec -T db psql -U vibestore -d vibestore < migrations/005_async_repository_indexing.sql
``

OpenAPI: http://localhost:8000/docs  
Health: http://localhost:8000/health

## API

- `GET /health`: database and Redis dependency health.
- `POST /api/v1/auth/register`: create an account and issue a short-lived access token.
- `POST /api/v1/auth/token`: exchange email/password for an access token.
- `GET /api/v1/auth/me`: return the authenticated account.
- `POST /api/v1/repositories/index`: synchronous authenticated indexing endpoint retained for compatibility.
- `POST /api/v1/repositories/index-jobs`: enqueue authenticated repository indexing and return a job ID (HTTP 202).
- `GET /api/v1/repositories/jobs/{job_id}`: poll the caller-owned job state, attempt count, error and resulting catalog app ID.
- `POST /api/v1/webhooks/github`: signed GitHub webhook endpoint; queues default-branch `push` deliveries and deduplicates delivery IDs.
- `GET /api/v1/repositories/mine`: list only the authenticated user's repository submissions.
- `DELETE /api/v1/repositories/mine/{app_id}`: remove the authenticated user's submission link without deleting the shared catalog app or its indexed files.
- `POST /api/v1/search`: PostgreSQL full-text search, upgraded to weighted lexical + cosine-similarity ranking when embeddings are configured and indexed.
- `POST /api/v1/repositories/inspect`: fetch a public GitHub repository and report declared Android permissions, selected Gradle SDK dependencies and manifest security heuristics.

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
- Login failures use a generic error response; Argon2 hashing/verification runs off the async event loop and unknown-account attempts use a dummy hash.
- Registration and login are rate-limited to 10 attempts per client IP per 15-minute Redis window. If Redis is unavailable, authentication attempts fail closed with HTTP 503.
- Access tokens are short-lived; refresh-token rotation, email verification, password reset, account recovery and MFA are not yet implemented. Do not expose this service to the public internet as a production identity provider until these controls are added.

## Background indexing and GitHub webhooks

The API enqueues jobs in Redis using Arq; the dedicated Compose `worker` service consumes them independently from the API process. The worker persists job state in PostgreSQL (`queued`, `running`, `retrying`, `completed`, `failed`), records attempt counts, retries transient failures up to five attempts with exponential backoff, and reuses the bounded GitHub fetcher. Jobs use deterministic IDs to avoid duplicate Redis enqueue operations. The worker also stores configured embeddings when AI is enabled. Apply `005_async_repository_indexing.sql` after migrations `001` through `004`.

Configure a random `GITHUB_WEBHOOK_SECRET` in `.env`, then register a GitHub repository webhook targeting `https://YOUR_API_HOST/api/v1/webhooks/github`, content type `application/json`, with the `push` event selected. The endpoint verifies `X-Hub-Signature-256` against the exact raw request body using constant-time comparison, caps payloads at 1 MB, ignores non-push and non-default-branch events, and deduplicates `X-GitHub-Delivery`. Only public canonical GitHub repository URLs are accepted.

Run the API and worker with `docker compose up --build -d`; check worker logs with `docker compose logs -f worker`.

## AI provider adapter

A provider-neutral `AIProvider` interface and OpenAI-compatible adapter are included. Configure `AI_PROVIDER=openai-compatible`, `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, and `AI_EMBEDDING_MODEL` to generate and store embeddings during repository indexing and to enable hybrid search. Use `AI_PROVIDER=none` to disable model calls. The vector column intentionally has no fixed dimension so compatible providers can supply different embedding sizes; similarity ranking currently uses a filtered sequential scan, not an approximate-nearest-neighbor index. Keep one stable embedding model/dimension per configured model name.

## Repository inspection limits

Repository files are fetched as data and never executed. The indexing endpoint accepts canonical GitHub repository URLs only, rejects truncated repository trees, caps retrieval to 12 candidate files and 1 MB per file, and stores bounded text excerpts. Current static inspection checks Android manifest permission declarations, cleartext-traffic/exported-component flags, and a curated set of analytics/attribution/crash SDK dependencies in Gradle files. Every SDK match includes file/line evidence and is explicitly marked as a dependency declaration, not proof of initialization or data transmission. Manifest warnings are line-level heuristics that require manual review. A declared permission does not prove runtime use. Private repositories are rejected even when a token is configured; `GITHUB_TOKEN` currently raises the public GitHub API rate limit only. GitLab/Codeberg integrations, tracker detection, architecture analysis and evidence-backed AI reports are not implemented yet.

## Remaining platform work

The initial schema enables pgvector and records catalog, repository file, inspection and remix-job metadata. Authenticated one-shot GitHub repository indexing, ownership-scoped submission management, stale-file replacement on re-index, and provider-backed embeddings/hybrid search are implemented. Scheduled periodic catalog refresh and reconciliation, comprehensive X-Ray analysis, remix agent/orchestration, isolated Gradle workers, isolated APK signing, artifact storage/delivery, notifications, richer catalog/discovery UX, full X-Ray and Remix screens remain outstanding. The remix table is groundwork only: no arbitrary repository code is built or signed by this API.

Production deployments must replace Compose credentials, use TLS, restrict CORS, protect secrets, verify webhook signatures, configure backup/restore, add observability, and keep builds in disposable network-restricted sandboxes. Signing keys must remain outside both the API and build workers.
