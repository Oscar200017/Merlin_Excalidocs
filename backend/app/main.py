import csv
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pypdf import PdfReader
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set. Put it in backend/.env")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

app = FastAPI(title="Merlin Docs")

@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}

@app.post("/import/manifest")
def import_manifest(manifest_path: str = "../storage/processed/manifest.csv"):
    p = Path(manifest_path).resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"manifest not found: {p}")

    inserted = 0
    skipped = 0

    with p.open("r", encoding="utf-8-sig") as f, engine.begin() as conn:
        reader = csv.DictReader(f)
        required = {"original_filename","stored_path","sha256","size_bytes","ext","category","year","last_write_time"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise HTTPException(
                status_code=400,
                detail=f"manifest missing columns. Found: {reader.fieldnames}"
            )

        for row in reader:
            exists = conn.execute(
                text("SELECT 1 FROM documents WHERE sha256 = :sha LIMIT 1"),
                {"sha": row["sha256"]}
            ).first()

            if exists:
                skipped += 1
                continue

            conn.execute(
                text("""
                    INSERT INTO documents
                      (original_filename, stored_path, sha256, size_bytes, ext, category, doc_year, last_write_time)
                    VALUES
                      (:original_filename, :stored_path, :sha256, :size_bytes, :ext, :category, :doc_year, :last_write_time)
                """),
                {
                    "original_filename": row["original_filename"],
                    "stored_path": row["stored_path"],
                    "sha256": row["sha256"],
                    "size_bytes": int(row["size_bytes"]),
                    "ext": row["ext"],
                    "category": row["category"],
                    "doc_year": int(row["year"]) if row.get("year") else None,
                    "last_write_time": row["last_write_time"],
                }
            )
            inserted += 1

    return {"inserted": inserted, "skipped": skipped, "manifest": str(p)}

@app.get("/search")
def search(q: str, category: Optional[str] = None, ext: Optional[str] = None, limit: int = 20):
    sql = """
      SELECT id, title, original_filename, category, ext, doc_year, stored_path,
             ts_rank_cd(content_tsv, websearch_to_tsquery('simple', :q)) AS rank
      FROM documents
      WHERE content_tsv @@ websearch_to_tsquery('simple', :q)
    """
    params = {"q": q}

    if category:
        sql += " AND category = :category"
        params["category"] = category
    if ext:
        sql += " AND ext = :ext"
        params["ext"] = ext

    sql += " ORDER BY rank DESC, doc_year DESC NULLS LAST LIMIT :limit"
    params["limit"] = limit

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    return {"count": len(rows), "results": rows}
    

@app.post("/process/pdfs")
def process_pdfs(limit: int = 50):
    """
    Extrae texto de PDFs ya importados y rellena content_text.
    El trigger se encarga de generar content_tsv.
    """
    processed = 0
    skipped = 0
    errors = 0

    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, stored_path, ext
            FROM documents
            WHERE (content_text IS NULL OR length(content_text) = 0)
            ORDER BY id ASC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()

        for r in rows:
            if r["ext"].upper() != "PDF":
                skipped += 1
                continue

            pdf_path = Path(r["stored_path"])
            if not pdf_path.exists():
                errors += 1
                continue

            try:
                reader = PdfReader(str(pdf_path))
                text_parts = []
                for page in reader.pages:
                    t = page.extract_text() or ""
                    if t:
                        text_parts.append(t)
                full_text = "\n\n".join(text_parts).strip()

                conn.execute(
                    text("UPDATE documents SET content_text = :t WHERE id = :id"),
                    {"t": full_text, "id": r["id"]}
                )
                processed += 1
            except Exception:
                errors += 1

    return {"processed": processed, "skipped": skipped, "errors": errors}