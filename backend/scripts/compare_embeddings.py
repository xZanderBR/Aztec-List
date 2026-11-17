"""
Parity check: local fastembed vs Cloudflare Workers AI embeddings.

Production embeds through Workers AI (EMBEDDING__PROVIDER=cloudflare) so the server
needs no local ONNX model. Run this before switching, to confirm the hosted model
produces vectors close enough to the local one that the semantic-search tuning
(VECTOR__SCORE_FLOOR / VECTOR__RELATIVE_MARGIN, see docs/06-semantic-search.md)
still holds. Run from backend/ with Cloudflare credentials in the environment:

    EMBEDDING__CLOUDFLARE_ACCOUNT_ID=... EMBEDDING__CLOUDFLARE_API_TOKEN=... \\
        uv run python scripts/compare_embeddings.py

Checks:
1. Per-text cosine similarity between the two backends' vectors (expect >= 0.98).
2. Ranking agreement: for each probe query, the top-3 listings from a small corpus
   should match between backends.

Exits non-zero if either check fails. Uses a few hundred embedding tokens of the
Workers AI free allocation.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.services.embeddings import (
    CloudflareEmbeddingService,
    EmbeddingService,
    listing_to_text,
)

MIN_COSINE = 0.98
TOP_K = 3

CORPUS = [
    ("Wooden study desk", "Solid oak desk with two drawers, fits a dorm room."),
    ("Ergonomic office chair", "Mesh back, adjustable lumbar support, barely used."),
    ("TI-84 Plus graphing calculator", "Works perfectly, needed for Calc 1 and Stats."),
    ("Mini fridge", "3.1 cu ft compact fridge with freezer box, great for dorms."),
    ("Grand Theft Auto V (PS5)", "Disc in great condition, includes the map."),
    ("Nintendo Switch OLED", "White model with dock and two Joy-Cons."),
    ("Road bike, 54cm", "Aluminum frame, Shimano 105 groupset, new tires."),
    ("Organic chemistry textbook", "Klein, 4th edition, light highlighting."),
    ("Noise-cancelling headphones", "Over-ear Bluetooth headphones, 30-hour battery."),
    ("Twin XL bedding set", "Comforter, sheets and two pillowcases, washed."),
    ("Desk lamp with USB port", "LED lamp, three brightness levels."),
    ("Skateboard", "Complete board, 8-inch deck, smooth bearings."),
]
QUERIES = [
    "something to study at",
    "gta",
    "math class calculator",
    "keep drinks cold in my room",
    "music while I walk to class",
    "bike to get to campus",
    "chem book",
]
PARITY_TEXTS = [listing_to_text(t, d) for t, d in CORPUS] + QUERIES


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
    return dot / norm


def _top_k(query: list[float], docs: list[list[float]]) -> list[int]:
    scores = sorted(((_cosine(query, d), i) for i, d in enumerate(docs)), reverse=True)
    return [i for _score, i in scores[:TOP_K]]


def main() -> int:
    local = EmbeddingService()
    hosted = CloudflareEmbeddingService()

    local_vecs = local.embed_documents(PARITY_TEXTS)
    hosted_vecs = hosted.embed_documents(PARITY_TEXTS)
    cosines = [_cosine(a, b) for a, b in zip(local_vecs, hosted_vecs, strict=True)]
    worst = min(cosines)
    print(f"Parity: min cosine {worst:.4f}, mean {sum(cosines) / len(cosines):.4f}")
    ok = worst >= MIN_COSINE

    corpus_text = [listing_to_text(t, d) for t, d in CORPUS]
    local_docs, hosted_docs = (
        local.embed_documents(corpus_text),
        hosted.embed_documents(corpus_text),
    )
    for query in QUERIES:
        a = _top_k(local.embed_query(query), local_docs)
        b = _top_k(hosted.embed_query(query), hosted_docs)
        same = a == b
        ok = ok and same
        titles = ", ".join(CORPUS[i][0] for i in b)
        print(f"{'OK  ' if same else 'DIFF'} {query!r}: {titles}")

    print("PASS" if ok else f"FAIL (need min cosine >= {MIN_COSINE} and identical top-{TOP_K})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
