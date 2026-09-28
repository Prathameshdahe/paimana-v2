"""app.rag_chunks and app.rag_meta: the assistant's search index (llm/rag.py) with its pgvector embeddings

Revision ID: 3e5f7a9b2c68
Revises: 2c8d4e6f1a57
Create Date: 2026-09-28

One row per chunk (the id, kind, visibility, project key, title, text, source, url and date of llm/rag.py's chunk
dicts, trusted as the hit flag, content_hash to reuse a vector when the text did not change, the embedding model's
name and a 768-wide nomic vector, null until embedded); rag_meta holds the fingerprint of the inputs the index was
built from. The HNSW index serves cosine nearest-neighbour search.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3e5f7a9b2c68"
down_revision: Union[str, Sequence[str], None] = "2c8d4e6f1a57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DIM = 768   # text-embedding-nomic-embed-text-v1.5 (llm/client.py LLM_EMBED_MODEL)


class Vector(sa.types.UserDefinedType):
    """pgvector's vector(n) column type, enough for the DDL (the Python side is a list of floats through psycopg)."""
    cache_ok = True

    def __init__(self, dim: int):
        self.dim = dim

    def get_col_spec(self, **kw):
        return f"vector({self.dim})"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column("project_key", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.Text()),
        sa.Column("url", sa.Text()),
        sa.Column("date", sa.Text()),
        sa.Column("trusted", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("model", sa.Text()),
        sa.Column("embedding", Vector(DIM)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("visibility IN ('public', 'official')", name="ck_rag_chunks_visibility"),
        schema="app",
    )
    op.create_index("rag_chunks_visibility", "rag_chunks", ["visibility"], schema="app")
    op.create_index("rag_chunks_project", "rag_chunks", ["project_key"], schema="app")
    op.create_index("rag_chunks_kind", "rag_chunks", ["kind"], schema="app")
    op.execute("CREATE INDEX rag_chunks_embedding ON app.rag_chunks USING hnsw (embedding vector_cosine_ops)")
    op.create_table(
        "rag_meta",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB()),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("rag_meta", schema="app")
    op.drop_table("rag_chunks", schema="app")
