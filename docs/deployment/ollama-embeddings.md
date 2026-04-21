# Using Ollama for local embeddings

As of Phase 7c sprint item S4, LV_DCP can run vector retrieval against
any OpenAI-compatible embeddings endpoint — including [Ollama](https://ollama.ai)'s
`/v1/embeddings`. No OpenAI API key required, no local Python model
download, no change to the Qdrant side of the stack.

## Quick start

### 1. Pull an embedding model in Ollama

```bash
# Recommended — balanced, 768-dim:
ollama pull nomic-embed-text

# Smaller, 384-dim:
ollama pull all-minilm

# Larger, 1024-dim, state-of-the-art English:
ollama pull mxbai-embed-large
```

### 2. Configure LV_DCP

Edit `~/.lvdcp/config.yaml`:

```yaml
qdrant:
  enabled: true
  url: http://localhost:6333

embedding:
  provider: ollama
  model: nomic-embed-text
  dimension: 768                          # must match the model!
  base_url: http://localhost:11434/v1     # default, override for remote

# for remote Ollama:
# embedding:
#   provider: ollama
#   model: nomic-embed-text
#   dimension: 768
#   base_url: https://ollama.example.com/ollama/v1
```

`api_key_env_var` is ignored when `provider: ollama` — Ollama accepts any
non-empty dummy string and LV_DCP supplies one automatically.

### 3. Drop existing Qdrant collections (if switching from OpenAI)

Changing the embedding `dimension` requires rebuilding the Qdrant
collections — vectors of different sizes can't coexist. Either:

```bash
# Drop all LV_DCP collections (fastest — next scan rebuilds them):
curl -X DELETE http://localhost:6333/collections/devctx_summaries
curl -X DELETE http://localhost:6333/collections/devctx_symbols
curl -X DELETE http://localhost:6333/collections/devctx_chunks
curl -X DELETE http://localhost:6333/collections/devctx_patterns
```

Or: keep the old collection around, configure a new Qdrant `url`
pointing at a separate instance for the Ollama-dimension data.

### 4. Rescan

```bash
ctx scan /path/to/your/project
```

The first scan will embed every file; subsequent scans only re-embed
content that changed (content-hash gated).

## Model dimension table

| Model                | Dimension | Notes                                    |
|----------------------|-----------|------------------------------------------|
| `all-minilm`         | 384       | Smallest / fastest; good for small corpora |
| `nomic-embed-text`   | 768       | **Recommended default.** Balanced.       |
| `mxbai-embed-large`  | 1024      | Best quality; 2x slower than nomic.      |
| `text-embedding-3-small` (OpenAI) | 1536 | Reference baseline.               |
| `text-embedding-3-large` (OpenAI) | 3072 | Highest quality.                  |

## Troubleshooting

### `embedding failed for <project>, continuing without vector index`

This warning in scan output means the Qdrant vector store is
unreachable or the adapter raised. Check:

1. `qdrant.enabled: true` and `qdrant.url` is reachable.
2. `provider: ollama` and `base_url` is correct (try
   `curl <base_url>/embeddings -d '{"model":"nomic-embed-text","input":"x"}'`
   manually).
3. The Ollama model is actually pulled (`ollama list`).
4. `dimension` in config matches the model's output dim.

Retrieval still works without the vector index (falls back to FTS +
symbol match + graph + centrality). The warning is non-fatal.

### Vector fusion seems to hurt recall

LV_DCP auto-disables vector fusion when the corpus is small or the top
cosine similarity is weak (see
`libs/retrieval/pipeline.compute_vector_fusion_weight`). This is by
design — on <100-file projects vector dilutes FTS precision. Nothing
to do; lexical retrieval handles it.

### Latency

`nomic-embed-text` on a modest Ollama box embeds ~200 texts/s. A fresh
scan of a 1000-file repo takes ~5 seconds for embedding + however long
the rest of the scan took. Remote Ollama adds network round-trip; the
client batches concurrently via `asyncio`.
