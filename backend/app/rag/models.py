"""The local embedding and reranking models, and the tokenizer that decides what fits.

Both run on the CPU through fastembed and are loaded once. Blocking: call from a worker thread.
"""

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
from tokenizers import Tokenizer

from app.rag.constants import EMBEDDING_DIM, MAX_EMBED_TOKENS, TooLongError

__all__ = [
    "EMBEDDING_DIM",
    "MAX_EMBED_TOKENS",
    "Embedder",
    "ModelConfig",
    "Reranker",
    "TooLongError",
]


@dataclass(frozen=True, slots=True)
class ModelConfig:
    embedding_model: str
    rerank_model: str
    cache_dir: Path


class Embedder:
    """Turns text into vectors, and counts tokens the way the embedding model does."""

    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self.model_name = model_name
        self._model = TextEmbedding(model_name, cache_dir=str(cache_dir))
        # A copy that does not truncate, so lengths are real (the model's own tokenizer stops
        # counting at 512).
        self._counter = Tokenizer.from_str(self._model.model.tokenizer.to_str())
        self._counter.no_truncation()
        self._counter.no_padding()
        self._lock = threading.Lock()  # one ONNX session; keep calls one at a time

    def count(self, text: str) -> int:
        """Tokens the model will read, including its two special tokens."""
        return len(self._counter.encode(text).ids)

    def tail(self, text: str, tokens: int) -> str:
        """The last `tokens` tokens of `text`, cut at a word boundary."""
        encoded = self._counter.encode(text, add_special_tokens=False)
        if len(encoded.ids) <= tokens:
            return text
        start = encoded.offsets[-tokens][0]
        cut = text[start:]
        space = text.rfind(" ", 0, start)
        return text[space + 1 :] if space >= 0 and start - space <= 12 else cut

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        for text in texts:
            if self.count(text) > MAX_EMBED_TOKENS:
                raise TooLongError(f"Text of {self.count(text)} tokens would be cut off")
        with self._lock:
            vectors = [vector.tolist() for vector in self._model.passage_embed(list(texts))]
        if vectors and len(vectors[0]) != EMBEDDING_DIM:
            raise RuntimeError(
                f"{self.model_name} gives {len(vectors[0])} dimensions; the database expects "
                f"{EMBEDDING_DIM}. Changing the embedding model needs a migration."
            )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        with self._lock:
            return next(iter(self._model.query_embed(text))).tolist()


class Reranker:
    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self._model = TextCrossEncoder(model_name, cache_dir=str(cache_dir))
        self._lock = threading.Lock()

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        with self._lock:
            return [float(score) for score in self._model.rerank(query, list(passages))]


@lru_cache
def get_embedder(config: ModelConfig) -> Embedder:
    return Embedder(config.embedding_model, config.cache_dir)


@lru_cache
def get_reranker(config: ModelConfig) -> Reranker:
    return Reranker(config.rerank_model, config.cache_dir)
