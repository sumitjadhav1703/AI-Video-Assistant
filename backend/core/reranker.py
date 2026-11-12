"""Mandatory TinyBERT reranking. Assets are prepared and pinned before serving."""
import hashlib
import json
import math
import os
import threading
from pathlib import Path

from .retrieval import RetrievalUnavailable

MODEL_NAME = 'ms-marco-TinyBERT-L-2-v2'
MODEL_FILES = ('flashrank-TinyBERT-L-2-v2.onnx', 'config.json', 'tokenizer.json',
               'tokenizer_config.json', 'special_tokens_map.json')
MANIFEST_PATH = Path(__file__).resolve().parents[1] / 'model_assets' / 'manifest.json'
_ranker = None
_ranker_path = None
_counter = None
_lock = threading.Lock()
_inference_lock = threading.Lock()


def verify_model_assets(directory):
    try:
        manifest = json.loads(MANIFEST_PATH.read_text())
        if manifest['model'] != MODEL_NAME or not all(name in manifest['files'] for name in MODEL_FILES):
            raise ValueError('Incomplete model manifest')
        for name, expected in manifest['files'].items():
            if Path(name).name != name or len(expected) != 64:
                raise ValueError('Invalid model manifest')
            digest = hashlib.sha256()
            with (directory / name).open('rb') as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError('Model asset checksum mismatch')
    except Exception as exc:
        raise RetrievalUnavailable('Verified local reranker assets are unavailable.') from exc


def load_ranker():
    global _ranker, _ranker_path, _counter
    directory = Path(os.getenv('RERANK_MODEL_DIR', str(MANIFEST_PATH.parent / MODEL_NAME))).resolve()
    with _lock:
        if _ranker is None or _ranker_path != directory:
            verify_model_assets(directory)
            try:
                import onnxruntime
                onnxruntime.disable_telemetry_events()
                from flashrank import Ranker
                class OfflineRanker(Ranker):
                    def _prepare_model_dir(self, model_name):
                        # FlashRank otherwise downloads absent weights during construction.
                        self.model_dir = directory
                        self.model_path = directory / MODEL_FILES[0]
                        if not self.model_path.is_file():
                            raise RetrievalUnavailable('Local reranker weights are missing.')

                _ranker = OfflineRanker(model_name=MODEL_NAME, cache_dir=str(directory.parent), max_length=512)
                _ranker_path = directory
                # A separate tokenizer measures original pairs without disabling runtime truncation.
                from tokenizers import Tokenizer
                _counter = Tokenizer.from_str(_ranker.tokenizer.to_str())
                _counter.no_truncation()
                _counter.no_padding()
            except RetrievalUnavailable:
                raise
            except Exception as exc:
                raise RetrievalUnavailable('Local reranker could not load.') from exc
        return _ranker


def rerank_documents(query, documents):
    if not 1 <= len(documents) <= 12:
        raise RetrievalUnavailable('Reranking requires between one and twelve fused candidates.')
    ranker = load_ranker()
    try:
        from flashrank import RerankRequest
        with _inference_lock:
            lengths = [len(_counter.encode(query, doc.page_content).ids) for doc in documents]
            passages = [{'id': doc.metadata['chunk_id'], 'text': doc.page_content} for doc in documents]
            ranked = ranker.rerank(RerankRequest(query=query, passages=passages))
        originals = {doc.metadata['chunk_id']: doc for doc in documents}
        positions = {doc.metadata['chunk_id']: i for i, doc in enumerate(documents)}
        if len(ranked) != len(originals) or {item['id'] for item in ranked} != set(originals):
            raise ValueError('Reranker returned unknown/duplicate IDs')
        if any(not math.isfinite(float(item['score'])) for item in ranked):
            raise ValueError('Reranker returned non-finite score')
        ranked.sort(key=lambda item: (-float(item['score']), positions[item['id']]))
        return [originals[item['id']] for item in ranked[:4]], {
            'model': MODEL_NAME, 'max_tokens': 512, 'truncated': any(length > 512 for length in lengths),
            'truncated_count': sum(length > 512 for length in lengths),
            'scores': [{'chunk_id': item['id'], 'rank': rank, 'score': float(item['score'])}
                       for rank, item in enumerate(ranked, 1)]}
    except RetrievalUnavailable:
        raise
    except Exception as exc:
        raise RetrievalUnavailable('Required reranking failed.') from exc
