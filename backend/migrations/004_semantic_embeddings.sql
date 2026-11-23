ALTER TABLE apps ADD COLUMN IF NOT EXISTS embedding vector;
ALTER TABLE apps ADD COLUMN IF NOT EXISTS embedding_model TEXT;
CREATE INDEX IF NOT EXISTS apps_embedding_model_idx ON apps(embedding_model) WHERE embedding IS NOT NULL;
