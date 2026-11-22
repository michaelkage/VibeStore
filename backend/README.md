# VibeStore API

FastAPI service foundation for VibeStore's Android discovery and repository-intelligence workflows. This is separate from the existing Flutter app and does not replace its app-source or installation pipeline.

## Run locally

```bash
cp .env.example .env
docker compose up --build
```

Apply the initial schema after PostgreSQL starts:

```bash
docker compose exec -T db psql -U vibestore -d vibestore < migrations/001_initial.sql
```

OpenAPI: http://localhost:8000/docs  
Health: http://localhost:8000/health

## Endpoints currently implemented

- `GET /health`: database-aware service health.
- `POST /api/v1/search`: PostgreSQL full-text catalog search.
- `POST /api/v1/repositories/inspect`: fetches public GitHub repository metadata/files and reports Android manifest permission declarations.

Inspection is static only. A declared permission does not prove runtime use. Repository source is treated as data and never executed.

## AI adapters

A provider-neutral `AIProvider` interface and OpenAI-compatible adapter are included. Configure `AI_PROVIDER=openai-compatible`, `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, and optionally `AI_EMBEDDING_MODEL`. Use `AI_PROVIDER=none` to disable model calls.

## Important remaining platform work

The schema enables pgvector but embedding ingestion/vector ranking, catalog indexing workers, authentication/authorization, webhook signature verification, Redis queue consumers, full X-Ray/tracker analysis, remix orchestration, isolated Gradle build workers, separate signing service, artifact storage, push notifications and Flutter UI integration are not implemented by this foundation. Do not expose remix operations until auth and ownership checks exist.

Production deployments must replace Compose credentials, use TLS, restrict CORS, protect secrets, verify webhook signatures, and keep builds in disposable network-restricted sandboxes. Signing keys must remain outside the API and build worker.
