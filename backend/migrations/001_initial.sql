CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS apps (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 package_name TEXT, name TEXT NOT NULL, description TEXT, repository_url TEXT NOT NULL UNIQUE,
 default_branch TEXT, stars INTEGER NOT NULL DEFAULT 0 CHECK (stars >= 0), license TEXT,
 latest_commit_sha TEXT, indexed_at TIMESTAMPTZ,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 search_document TSVECTOR GENERATED ALWAYS AS (
  setweight(to_tsvector('english', coalesce(name,'')), 'A') ||
  setweight(to_tsvector('english', coalesce(description,'')), 'B') ||
  setweight(to_tsvector('english', coalesce(package_name,'')), 'A')
 ) STORED
);
CREATE INDEX IF NOT EXISTS apps_search_document_idx ON apps USING GIN(search_document);
CREATE INDEX IF NOT EXISTS apps_stars_idx ON apps(stars DESC);
CREATE TABLE IF NOT EXISTS repository_files (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), app_id UUID NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
 path TEXT NOT NULL, content_sha TEXT NOT NULL, language TEXT, content_excerpt TEXT,
 indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(app_id,path,content_sha)
);
CREATE INDEX IF NOT EXISTS repository_files_app_idx ON repository_files(app_id);
CREATE TABLE IF NOT EXISTS inspections (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), app_id UUID NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
 commit_sha TEXT NOT NULL, report JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(app_id,commit_sha)
);
CREATE TABLE IF NOT EXISTS remix_jobs (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), app_id UUID NOT NULL REFERENCES apps(id),
 owner_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued'
 CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
 prompt TEXT NOT NULL, source_commit_sha TEXT, output_artifact_key TEXT, error_code TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
