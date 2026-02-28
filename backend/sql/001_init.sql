-- 001_init.sql (FIXED)
-- Extensiones
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Tabla principal
CREATE TABLE IF NOT EXISTS documents (
  id BIGSERIAL PRIMARY KEY,
  original_filename TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  sha256 CHAR(64) NOT NULL UNIQUE,
  size_bytes BIGINT NOT NULL,
  ext TEXT NOT NULL,
  category TEXT NOT NULL,
  doc_year INT,
  last_write_time TIMESTAMPTZ,

  title TEXT,
  author TEXT,
  doc_date DATE,

  content_text TEXT,
  content_tsv tsvector,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_documents_tsv ON documents USING GIN (content_tsv);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents (category);
CREATE INDEX IF NOT EXISTS idx_documents_doc_year ON documents (doc_year);
CREATE INDEX IF NOT EXISTS idx_documents_ext ON documents (ext);
CREATE INDEX IF NOT EXISTS idx_documents_title_trgm ON documents USING GIN (title gin_trgm_ops);

-- Función trigger (tsvector + updated_at)
CREATE OR REPLACE FUNCTION documents_tsv_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.content_tsv :=
    setweight(to_tsvector('simple', COALESCE(NEW.title, '')), 'A') ||
    setweight(to_tsvector('simple', COALESCE(NEW.content_text, '')), 'B');
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- Trigger (si existe, lo recreamos)
DROP TRIGGER IF EXISTS trg_documents_tsv ON documents;

CREATE TRIGGER trg_documents_tsv
BEFORE INSERT OR UPDATE OF title, content_text
ON documents
FOR EACH ROW
EXECUTE FUNCTION documents_tsv_update();