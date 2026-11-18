"""ChromaDB index over AST chunks, plus a symbol table for exact lookups.

Retrieval for a file combines two signals (after RepoCoder, 2023):
  1. symbol lookup  - definitions (in other files) of functions/types the file references
  2. similarity     - nearest chunks by embedding

The default embedder is an offline hashing embedder over code identifiers,
so indexing works with no model download. Set MODERNIZER_EMBEDDER to a
sentence-transformers model name (e.g. "all-MiniLM-L6-v2") to use one.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path

from .chunking import Chunk, chunk_repo, chunk_source

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _tokens(text: str) -> list[str]:
    out = []
    for word in _IDENT.findall(text):
        out.append(word.lower())
        for piece in _CAMEL.sub("_", word).lower().split("_"):
            if piece and piece != word.lower():
                out.append(piece)
    return out


class HashingEmbedder:
    def __init__(self, dim: int = 512):
        self.dim = dim

    def __call__(self, texts: list[str]) -> list[list[float]]:
        vecs = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in _tokens(t):
                h = int.from_bytes(hashlib.md5(tok.encode()).digest()[:4], "little")
                v[h % self.dim] += 1.0 if (h >> 31) & 1 else -1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            vecs.append([x / n for x in v])
        return vecs


class STEmbedder:
    def __init__(self, model: str):
        from sentence_transformers import SentenceTransformer

        self._m = SentenceTransformer(model)

    def __call__(self, texts: list[str]) -> list[list[float]]:
        return self._m.encode(texts, normalize_embeddings=True).tolist()


def default_embedder():
    name = os.environ.get("MODERNIZER_EMBEDDER")
    return STEmbedder(name) if name else HashingEmbedder()


class CodeIndex:
    COLLECTION = "chunks"

    def __init__(self, index_dir: Path, embedder=None):
        import chromadb

        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.embed = embedder or default_embedder()
        self._client = chromadb.PersistentClient(path=str(self.index_dir / "chroma"))
        self._col = self._client.get_or_create_collection(
            self.COLLECTION, embedding_function=None, metadata={"hnsw:space": "cosine"})
        self._symbols_path = self.index_dir / "symbols.json"
        self.symbols: dict[str, list[dict]] = (
            json.loads(self._symbols_path.read_text()) if self._symbols_path.exists() else {})

    # ---- building -------------------------------------------------------
    def build(self, repo: Path, lang: str) -> int:
        chunks = chunk_repo(Path(repo), lang)
        existing = self._col.get(include=[])["ids"]
        if existing:
            self._col.delete(ids=existing)
        self.symbols = {}
        if not chunks:
            self._symbols_path.write_text("{}")
            return 0
        docs = [f"{c.header()}\n{c.text}" for c in chunks]
        self._col.add(
            ids=[c.id for c in chunks],
            documents=docs,
            embeddings=self.embed(docs),
            metadatas=[{"path": c.path, "kind": c.kind, "name": c.name,
                        "start": c.start_line, "end": c.end_line} for c in chunks],
        )
        for c, d in zip(chunks, docs):
            for sym in c.defines:
                if c.kind == "prototype":
                    continue  # prefer real definitions
                self.symbols.setdefault(sym, []).append({"id": c.id, "path": c.path, "doc": d})
        self._symbols_path.write_text(json.dumps(self.symbols))
        return len(chunks)

    def __len__(self) -> int:
        return self._col.count()

    # ---- retrieval ------------------------------------------------------
    def context_for(self, source: str, path: str, lang: str, k: int = 6) -> list[str]:
        """Repo context for migrating `path`: dependency definitions first, then similar code."""
        own = chunk_source(source, path, lang)
        own_defs = {d for c in own for d in c.defines}
        picked: dict[str, str] = {}

        for c in own:
            for ref in c.refs:
                if ref in own_defs:
                    continue
                for hit in self.symbols.get(ref, []):
                    if hit["path"] != path and len(picked) < k:
                        picked.setdefault(hit["id"], hit["doc"])

        if len(picked) < k and len(self):
            res = self._col.query(query_embeddings=self.embed([source]),
                                  n_results=min(len(self), k * 3), include=["documents", "metadatas"])
            for cid, doc, meta in zip(res["ids"][0], res["documents"][0], res["metadatas"][0]):
                if meta["path"] != path and len(picked) < k:
                    picked.setdefault(cid, doc)
        return list(picked.values())
