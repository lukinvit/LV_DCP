# Vector retrieval eval — sample_repo fixture (2026-04-16)

First run of FTS-only vs FTS+vector (RRF fusion) retrieval on the 23-file
synthetic `sample_repo` fixture using real OpenAI `text-embedding-3-small`
embeddings stored in Qdrant.

## Results

| Metric | FTS-only | FTS + vector | Delta |
|---|---|---|---|
| recall@5 files | 0.964 | 0.885 | **−0.078** |
| precision@3 files | 0.693 | 0.479 | **−0.214** |
| impact_recall@5 | 0.931 | 0.819 | **−0.111** |

**Verdict:** vector fusion regresses quality on this fixture.

## Why

1. Only 23 files embedded → cosine search returns low-confidence nearest
   neighbours that are not the lexical match.
2. RRF (`k=60`, equal weight) blends those low-confidence hits with strong
   FTS ranks, dropping top FTS targets out of the top-3.
3. `sample_repo` queries (e.g. `"session factory"`, `"FastAPI app entrypoint"`)
   already hit the correct file by identifier — FTS is near-ceiling; vector
   has nothing to add, only dilutes.

## Implications

- Vector retrieval is **not** a drop-in win. On lexically-unambiguous small
  corpora it hurts. Needs either:
  a. Dataset-dependent weighting (scale vector RRF contribution by corpus size
     or query ambiguity)
  b. Semantic-first queries in the eval set (e.g. "how does retry work?" —
     no obvious identifier) to show vector's real advantage
  c. Rank-threshold cutoff — only include vector hits above a similarity
     threshold
- This confirms the Phase 6/7 roadmap note that vector tuning is deferred.
  We should keep synthetic eval on FTS-only until we either expand the fixture
  or shift the fixture toward semantic queries.

## Repro

```bash
# ~/.lvdcp/config.yaml must have qdrant.enabled=true and embedding.provider=openai
ctx scan --full tests/eval/fixtures/sample_repo
uv run python /tmp/vector_eval.py
```

Harness: `/tmp/vector_eval.py` (ad-hoc, not committed — lives outside repo).
