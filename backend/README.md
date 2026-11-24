# VibeStore API

FastAPI service for VibeStore discovery and repository intelligence. It is separate from the existing Flutter app and preserves the Obtainium-derived app-source and installer pipeline.

## Local development

Requirements: Docker Compose and Python 3.11+ (Python is needed only for tests outside Docker).

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the generated value in `JWT_SECRET_KEY`. Generate a separate random secret for `GITHUB_WEBHOOK_SECRET` if webhook ingestion will be enabled. Then start the services and apply migrations in order:

```bash
docker compose up --build -d
docker compose exec -T db psql -U vibestore -d vibestore < migrations/001_initial.sql
docker compose exec -T db psql -U vibestore -d vibestore < migrations/002_authentication.sql
docker compose exec -T db psql -U vibestore -d vibestore < migrations/003_repository_submissions.sql
docker compose exec -T db psql -U vibestore -d vibestore < migrations/004_semantic_embeddings.sql
docker compose exec -T db psql -U vibestore -d vibestore < migrations/005_async_repository_indexing.sql
docker compose exec -T db psql -U vibestore -d vibestore < migrations/006_catalog_refresh_reconciliation.sql
docker compose exec -T db psql -U vibestore -d vibestore < migrations/007_cached_inspection_reports.sql
docker compose exec -T db psql -U vibestore -d vibestore < migrations/008_remix_sessions.sql
docker compose exec -T db psql -U vibestore -d vibestore < migrations/009_remix_patch_proposals.sql
docker compose exec -T db psql -U vibestore -d vibestore < migrations/010_remix_patch_validation.sql
```

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
- `GET /api/v1/apps/{app_id}/inspection`: return the latest cached inspection report, including its source commit SHA.
- `POST /api/v1/remixes`: create an owner-scoped planning session pinned to the app's current indexed commit.
- `GET /api/v1/remixes`: list the authenticated user's remix sessions.
- `GET /api/v1/remixes/{remix_id}`: retrieve an owned session and its conversation.
- `POST /api/v1/remixes/{remix_id}/messages`: append a prompt and generate an evidence-bounded change plan (requires a configured AI provider).
- `POST /api/v1/remixes/{remix_id}/proposals`: generate a structured unified-diff proposal against indexed file paths and hashes.
- `GET /api/v1/remixes/{remix_id}/proposals`: list proposals belonging to an owned remix session, including persisted validation reports.
- `POST /api/v1/remixes/{remix_id}/proposals/{proposal_id}/validate`: retrieve complete source blobs at the pinned commit, verify Git tree/blob hashes, and check all diff hunks in memory.
- `POST /api/v1/remixes/{remix_id}/proposals/{proposal_id}/review`: approve a proposal only after successful source validation, or reject it at any time; approval records a human decision and never applies the diff.

## Authentication security

- Passwords are hashed with Argon2 through pwdlib; plaintext passwords are never stored.
- Access tokens are signed HS256 JWTs with issuer, issue time and expiry claims.
- `JWT_SECRET_KEY` must be a unique random value of at least 32 characters. Never commit it.
- Account email addresses are normalized to lowercase and protected by a unique database index.
- Login failures use a generic error response; Argon2 hashing/verification runs off the async event loop and unknown-account attempts use a dummy hash.
- Registration and login are rate-limited to 10 attempts per client IP per 15-minute Redis window. If Redis is unavailable, authentication attempts fail closed with HTTP 503.
- Access tokens are short-lived; refresh-token rotation, email verification, password reset, account recovery and MFA are not yet implemented. Do not expose this service as a production identity provider until these controls are added.

## Background indexing, refresh and reconciliation

The API enqueues jobs in Redis using Arq; the dedicated Compose `worker` service consumes them independently from the API process. The worker persists job state in PostgreSQL (`queued`, `running`, `retrying`, `completed`, `failed`), records attempt counts, retries failures up to five attempts with exponential backoff, and reuses the bounded GitHub fetcher. Jobs use deterministic IDs to avoid duplicate Redis enqueue operations. The worker stores configured embeddings when AI is enabled. Each successful indexing pass also stores a commit-keyed static inspection report. When an AI provider is configured, the worker adds a short evidence-constrained explanation; provider errors do not discard deterministic findings or fail repository indexing.

The same worker runs a scheduled reconciliation every 15 minutes and once at startup. It:

1. Finds catalog apps whose `indexed_at` is older than `CATALOG_REFRESH_INTERVAL_DAYS` (default 7 days), with a bounded batch size.
2. Creates one scheduled refresh job per repository only when no queued, running or retrying job already exists. Transaction-scoped PostgreSQL advisory locks prevent duplicate scheduled jobs across worker replicas.
3. Repairs durable `queued` jobs by re-enqueuing their deterministic Arq IDs, covering the database-commit/Redis-enqueue failure window.
4. Recovers jobs left `running` beyond `INDEXING_STALE_JOB_MINUTES` (default 15) after a worker interruption, then re-enqueues them.

The scheduler does not delete catalog entries when a repository is unavailable; failed refreshes retain the last known-good catalog snapshot and record the job error. Refresh is bounded by `CATALOG_REFRESH_BATCH_SIZE` (default 50) per tick; queued recovery is bounded by `INDEXING_RECONCILE_BATCH_SIZE` (default 100). Apply `006_catalog_refresh_reconciliation.sql` after migrations `001` through `005`, then apply `007_cached_inspection_reports.sql`.

Configure a random `GITHUB_WEBHOOK_SECRET` in `.env`, then register a GitHub repository webhook targeting `https://YOUR_API_HOST/api/v1/webhooks/github`, content type `application/json`, with the `push` event selected. The endpoint verifies `X-Hub-Signature-256` against the exact raw request body using constant-time comparison, caps payloads at 1 MB, ignores non-push and non-default-branch events, and deduplicates `X-GitHub-Delivery`. A repeated delivery can recover an enqueue that previously failed because Redis was unavailable. Only public canonical GitHub repository URLs are accepted.

Run the API, indexing worker and isolated patch worker with `docker compose up --build -d`; inspect logs with `docker compose logs -f worker patch-worker`. The patch worker has no external network route: it runs on an internal-only Docker network shared with PostgreSQL and Redis, with a read-only container filesystem, a bounded `noexec` temporary filesystem, dropped Linux capabilities, no-new-privileges, a process cap and a memory cap. The API retrieves and verifies the immutable GitHub source snapshot before persisting a bounded handoff for this worker. The patch worker rechecks Git blob hashes and applies only already-approved unified diffs; it does not invoke shell commands, Gradle, repository scripts or build tools.

## AI provider adapter

A provider-neutral `AIProvider` interface and OpenAI-compatible adapter are included. Configure `AI_PROVIDER=openai-compatible`, `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, and `AI_EMBEDDING_MODEL` to generate and store embeddings during repository indexing and enable hybrid search. Use `AI_PROVIDER=none` to disable model calls. The vector column intentionally has no fixed dimension so compatible providers can supply different embedding sizes; similarity ranking currently uses a filtered sequential scan, not an approximate-nearest-neighbor index. Keep one stable embedding model/dimension per configured model name.

## Repository inspection limits

Repository files are fetched as data and never executed. The indexing endpoint accepts canonical GitHub repository URLs only, rejects truncated repository trees, caps retrieval to 12 candidate files and 1 MB per file, and stores bounded text excerpts. Current static inspection checks Android manifest permission declarations, cleartext-traffic/exported-component flags, a curated set of analytics/attribution/crash SDK dependencies in Gradle files, and coarse architecture indicators from repository paths. Reports are cached by app and source commit SHA and can be read from the cached inspection endpoint. When configured, the AI provider writes a concise explanation based only on extracted static evidence; the deterministic findings remain authoritative. SDK matches are dependency declarations, not proof of initialization or data transmission. Manifest warnings are line-level heuristics that require manual review. A declared permission does not prove runtime use. These reports are not a complete call-graph, data-flow or runtime tracker audit. Private repositories are rejected even when a token is configured; `GITHUB_TOKEN` currently raises the public GitHub API rate limit only. GitLab/Codeberg integrations and runtime tracker detection are not implemented.

## Remaining platform work

Comprehensive X-Ray analysis, full remix agent/orchestration, isolated Gradle workers, isolated APK signing, long-term artifact storage/delivery and notifications remain outstanding. Remix planning, source diff generation and pinned-source applicability validation are implemented, but this API still does not modify repository files, build arbitrary repository code or sign APKs.

Production deployments must replace Compose credentials, use TLS, restrict CORS, protect secrets, configure backups and observability, and keep builds in disposable network-restricted sandboxes. Signing keys must remain outside both the API and build workers.


## Fork & Vibe: remix planning foundation

Migration `008_remix_sessions.sql` adds owner-scoped remix sessions and conversation messages. A session records the app's current indexed commit SHA at creation. Planning requests are rejected with HTTP 409 if the catalog has since advanced, preventing a conversation pinned to an older revision from silently using newer indexed files. Session reads and writes are scoped to the authenticated owner.

The first implementation is deliberately a **planning-only** slice. A configured provider receives the latest bounded conversation and at most 12 indexed file excerpts (up to 6,000 characters each), selected with Android manifests and Gradle files prioritized. The prompt treats repository content as untrusted evidence and asks for a Markdown plan with affected paths, steps, risks and validation. Assistant messages store the evidence file paths used. Prompt and response sizes are bounded. Redis enforces a fail-closed limit of 30 AI planning requests per account per hour.

No source files are modified. No repository code, Gradle task, shell command or APK is executed. There is no cloud build, signing-key handling, artifact storage or delivery in this slice. Those capabilities require a separate disposable, network-restricted build environment and isolated signing service; they must not be added to the API process.


## Reviewable remix patch proposals

Migration `009_remix_patch_proposals.sql` stores structured AI-authored patch drafts under the owner-scoped remix session. Every proposal is pinned to the session's base commit SHA and records the indexed Git blob hashes for the affected files. The generator is restricted to the indexed path allowlist, accepts only bounded unified diffs with matching file headers and hunks, rejects traversal/absolute paths, duplicate paths, binary patches and oversized responses, and never accepts new/deleted/renamed files. Indexing fetches the tree and raw files from the same captured commit SHA so branch movement cannot mix snapshots.

Proposal review states are `proposed` → `approved` or `rejected`; validation states are `review_only`, `applicable` or `invalid`. Review transitions are owner-scoped and can occur only once. Migration `010_remix_patch_validation.sql` stores the validation report. The validation endpoint retrieves the Git commit and recursive tree, confirms every affected path points to the indexed Git blob SHA, downloads each complete blob (maximum 1 MB per file), recomputes the canonical Git blob SHA-1, requires UTF-8 text, and checks each unified-diff hunk against the exact source lines in memory. It rejects stale revisions, mismatched context and no-op diffs. **Approval is available only after validation succeeds; it is still an acknowledgement for human review and does not apply patches, write to GitHub, modify a checkout, run commands or build an APK.** Validation is not compilation or runtime testing. The processing endpoint is a separate explicit action after human approval. It writes only into a fresh disposable workspace and returns a ZIP containing changed files plus a provenance manifest; it never changes the original repository or source revision. The artifact is review-only and does not represent a complete checkout or a successful build.
