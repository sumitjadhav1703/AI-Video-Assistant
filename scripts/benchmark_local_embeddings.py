"""Compare retrieval stages with actual local embeddings and synthetic labels."""
import argparse
import hashlib
import json
import platform
import resource
import sys
from pathlib import Path
from time import perf_counter

from scripts.benchmark_retrieval import metrics

ASSETS = {
    "model_optimized.onnx": "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431",
    "tokenizer.json": "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
}
PASSAGES = (
    "Alice will present the Friday demo. Ben will run the rehearsal on Thursday.",
    "The launch moved to Tuesday because the accessibility review is pending.",
    "Dana checks keyboard navigation and captions before publication.",
    "The database upgrade is assigned to Bob. Priya owns database backups.",
    "The main storage engine is PostgreSQL and the vector extension is pgvector.",
    "Review the quarterly spending forecast on Monday in the Cedar room.",
    "The Cedar room is also booked on Wednesday for the design workshop.",
    "No production credentials may be included in the demonstration.",
    "Delete the temporary recording after the transcript is saved.",
    "The demo uses an invented transcript to protect participant privacy.",
    "The team will rehearse the onboarding session next month.",
    "The retry budget is two attempts per question, including the original request.",
    "A quiz at the end of onboarding measures whether participants followed along.",
    "During the exercise, the backups are encrypted before leaving the workstation.",
    "The projector needs a USB-C adapter. The spare is in the cabinet.",
    "The release notes cover how to add captions to pre-recorded videos.",
)
QUESTIONS = (
    ("Who is leading the live walkthrough on Friday?", {0}),
    ("Why was the release pushed back?", {1}),
    ("Who verifies that people can navigate without a mouse?", {2}),
    ("Who is in charge of migrating the database?", {3}),
    ("What database extension holds embeddings?", {4}),
    ("When do we discuss the financial projection?", {5}),
    ("What is Cedar being used for on Wednesday?", {6}),
    ("Which sensitive access information must stay out of the demo?", {7}),
    ("What happens to the source media after the transcript is stored?", {8}),
    ("How many calls at most can one chat question make?", {11}),
    ("How do we check what participants learned?", {12}),
    ("Where is the backup connector for the projector?", {14}),
)


def run(asset_dir):
    import numpy as np
    import onnxruntime as ort
    from langchain_core.documents import Document
    from tokenizers import Tokenizer

    from backend.core.reranker import load_ranker, rerank_documents
    from backend.core.retrieval import reciprocal_rank_fusion, sparse_candidates

    for filename, expected in ASSETS.items():
        with (asset_dir / filename).open("rb") as asset:
            if hashlib.file_digest(asset, "sha256").hexdigest() != expected:
                raise ValueError(f"Unexpected hash for {filename}")
    ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    started = perf_counter()
    tokenizer = Tokenizer.from_file(str(asset_dir / "tokenizer.json"))
    tokenizer.enable_padding()
    tokenizer.enable_truncation(max_length=512)
    session = ort.InferenceSession(str(asset_dir / "model_optimized.onnx"), options, providers=["CPUExecutionProvider"])
    load_seconds = perf_counter() - started

    def embed(texts):
        encoded = tokenizer.encode_batch(texts)
        inputs = {name: np.array([getattr(item, attribute) for item in encoded], dtype=np.int64)
                  for name, attribute in (("input_ids", "ids"), ("attention_mask", "attention_mask"),
                                          ("token_type_ids", "type_ids"))}
        vectors = session.run(["last_hidden_state"], inputs)[0][:, 0, :]
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        assert vectors.shape == (len(texts), 384) and np.isfinite(vectors).all() and (norms > 0).all()
        return vectors / norms

    documents = [Document(id=str(i), page_content=passage, metadata={"ordinal": i, "chunk_id": str(i)})
                 for i, passage in enumerate(PASSAGES)]
    started = perf_counter()
    index = embed(PASSAGES)
    corpus_seconds = perf_counter() - started
    started = perf_counter()
    load_ranker()
    reranker_load_seconds = perf_counter() - started
    results = []
    for question, labels in QUESTIONS:
        relevant = {str(i) for i in labels}
        started = perf_counter()
        vector = embed(["Represent this sentence for searching relevant passages: " + question])[0]
        dense = [documents[i] for i in np.argsort(-(index @ vector), kind="stable")[:10]]
        dense_seconds = perf_counter() - started
        started = perf_counter()
        fused = reciprocal_rank_fusion([dense, sparse_candidates(documents, question, 10)], 12)
        hybrid_seconds = perf_counter() - started
        started = perf_counter()
        reranked, _ = rerank_documents(question, fused)
        rerank_seconds = perf_counter() - started
        stages = {"dense": dense, "hybrid": fused, "reranked": reranked}
        results.append({
            "query": question, "relevant_ids": sorted(relevant),
            "seconds": {"dense": dense_seconds, "hybrid": hybrid_seconds, "rerank": rerank_seconds},
            "stages": {stage: {"ranking": [doc.id for doc in ranking],
                               **metrics([doc.id for doc in ranking], relevant, 4)}
                       for stage, ranking in stages.items()},
        })
    return {
        "model": "Qdrant/bge-small-en-v1.5-onnx-Q",
        "scope": "Single synthetic English fixture; in-memory exact cosine search; no provider, API or database workload.",
        "platform": platform.platform(), "dimensions": 384, "artifact_bytes": {
            name: (asset_dir / name).stat().st_size for name in ASSETS
        },
        "embedding_load_seconds": load_seconds, "corpus_embedding_seconds": corpus_seconds,
        "reranker_load_seconds": reranker_load_seconds,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        "means_at_4": {stage: {metric: sum(row["stages"][stage][metric] for row in results) / len(results)
                              for metric in ("recall_at_k", "reciprocal_rank")}
                       for stage in ("dense", "hybrid", "reranked")},
        "comparisons": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("asset_dir", type=Path)
    print(json.dumps(run(parser.parse_args().asset_dir), indent=2))
