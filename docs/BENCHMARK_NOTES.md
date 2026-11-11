# Offline retrieval fixture and reranker measurement

Run from the repository root with the locked dependencies and prepared, checksum-verified local model assets:

```sh
.venv/bin/python -m scripts.benchmark_retrieval > output/retrieval_benchmark.json
```

The report contains fixed, labelled synthetic examples and hand-authored dense rankings. BM25, RRF, and the real local TinyBERT reranker operate on those fixtures. The results demonstrate functional behavior only; they do not measure embedding-provider retrieval quality or establish real-world answer quality. Recall and reciprocal rank are measured at four. The stress case checks the singleton, times cold load and first inference separately from warm calls, and verifies 12 overlength inputs are truncated to at most 512 tokens. Process peak RSS includes the Python process and loaded libraries; its platform-specific units are included in the JSON. This is not a full application memory measurement.

One macOS arm64 run on Python 3.11.15, FlashRank 0.2.10 and onnxruntime 1.31.1: cold/warm load 0.098/0.000083 seconds; first/warm stress inference 0.085/0.084 seconds; process peak RSS 274,120,704 bytes. All 12 input pairs were truncated and the maximum encoded length was 512. Measurements are single observations, not latency distributions or a deployment capacity claim. JSON is in the ignored `output/` directory and can be regenerated.

For a reproducible 512 MiB Linux container gate, use an already-built local backend image with its dependencies installed and the verified local model assets in this checkout. This runs without network access; a successful exit confirms only this benchmark workload fits the container limit:

```sh
docker run --rm --network none --memory 512m --memory-swap 512m \
  -v "$PWD:/work:ro" -w /work --entrypoint python ai-video-backend \
  -m scripts.benchmark_retrieval > output/retrieval_benchmark_linux.json
```

For the wider import footprint, run the following. It imports the API, LiteLLM and LangChain LiteLLM before running the same real reranker workload. It disables dotenv loading, clears provider configuration, disables tracing and uses LiteLLM's bundled cost map. Socket connections are blocked throughout the measured run. It does not start an ASGI server, access a database, process audio or generate an answer.

```sh
.venv/bin/python -m scripts.benchmark_retrieval --full-service > output/retrieval_full_service_benchmark.json
```

One macOS arm64 full-service-import run peaked at 466,157,568 bytes (about 444.6 MiB); all 12 stress pairs were truncated to at most 512 tokens. These are single-process peak RSS measurements, not the full cgroup memory usage or a full-service load test.

The following stricter gate checks Linux, bounds the container at 512 MiB, and fails when process peak RSS exceeds 450 MiB. The remaining headroom is not a guarantee against cgroup exhaustion:

```sh
docker run --rm --network none --memory 512m --memory-swap 512m \
  -v "$PWD:/work:ro" -w /work --entrypoint python ai-video-backend \
  -m scripts.benchmark_retrieval --full-service --require-linux --max-rss-mib 450 \
  > output/retrieval_full_service_linux.json
```

Docker was unavailable on the measured host, so neither Linux gate has been run. The macOS RSS measurement does not establish Linux container memory compliance.

## Optional local embedding experiment

The same BM25, RRF and FlashRank code ran with real 384-dimensional embeddings from quantized BGE-small on one arm64 Mac. The benchmark used exact cosine search over 16 synthetic English passages and 12 manually labelled questions. It did not start the API, use PostgreSQL, or call a provider.

| Retrieval at four | Recall | Mean reciprocal rank |
| --- | ---: | ---: |
| Dense only | 1.000 | 0.896 |
| Dense + BM25 + RRF | 0.917 | 0.736 |
| Dense + BM25 + RRF + TinyBERT | 0.833 | 0.750 |

Reranking restored first place for two questions relative to RRF but dropped a third question's relevant passage out of the top four. This fixture exposes ranking trade-offs. It cannot estimate quality on real video transcripts, across languages, or with hosted Gemini embeddings.

The model and tokenizer total 67,176,520 bytes. One run measured 111 ms for model and tokenizer load, 174 ms to embed the passages, and median per-question increments of 12.5 ms for embedding and cosine search, 0.28 ms for BM25 and fusion, and 13.5 ms for reranking. Peak RSS for the experiment process was 326.3 MiB. Keep this model offline until representative evaluation and a joint hosting benchmark justify adding it.

To reproduce, download the two exact artifacts into the ignored output directory and run the offline script. The script checks both hashes before opening either artifact for inference. The pinned model revision is `aa8f8b060edb00e03bfdd08813a2949946c8ba55`. [Qdrant model card](https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q)

```sh
mkdir -p output/local-embedding
for file in model_optimized.onnx tokenizer.json; do
  curl --fail --location \
    "https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q/resolve/aa8f8b060edb00e03bfdd08813a2949946c8ba55/$file" \
    --output "output/local-embedding/$file" || break
done
.venv/bin/python -m scripts.benchmark_local_embeddings output/local-embedding \
  > output/local-embedding/report.json
```
