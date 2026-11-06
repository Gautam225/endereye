"""Limits that the database and the chunker share with the embedding model."""

EMBEDDING_DIM = 384  # the `vector(384)` column; a different model needs a new migration
MAX_EMBED_TOKENS = 512  # what bge-small reads; anything after is silently dropped


class TooLongError(ValueError):
    """Text that the embedder would cut off. Chunking must never let this happen."""
