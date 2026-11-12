# Code simplification

## Audit 2 — 13 November 2026

| Change | Why | Behaviour check |
| --- | --- | --- |
| `guardrails.py` drops `langchain.agents.middleware.pii` | A 48 MiB import for two regexes the module already had | 15,842 LangChain matches, 0 not covered locally |
| `retrieval.sparse_candidates` uses `rank_bm25.BM25Okapi` directly | `BM25Retriever` is a thin wrapper; this removes `langchain-community` and its 7 transitive packages | 0 of 500 rankings differ |
| Removed `transcribe_chunk`, `transcribe_chunk_groq`, `transcribe_chunk_sarvam`, `transcribe_all` | Not called by the app; tests now use `transcribe_segments` / `_chunk_segments` | Provider-guard tests retargeted |
| Removed `extract_action_items`, `extract_key_decisions`, `extract_questions`, `extractor.get_llm` | Each wrapper repeated the full extraction call; only `extract_findings` is used | Gateway test retargeted |
| `extractor._numbered` validation moved into the schema (`StringConstraints`) | The check ran after the paid call; the schema check triggers route fallback | B5 test |
| `rag_engine._locate_quote` uses one `re.search` | Replaced a hand-rolled exact-then-lowercase search | Evidence tests |
| `vector_store._store` | One constructor for both build and load paths | DB tests |
| `reranker`: tokenizer built at load | Rebuilt from JSON on every request | Retrieval tests |
| Frontend: dead tier select and state, `sourceLink`, `CODE`, unused `model`/`retrieval` chat fields | Never rendered or reachable | Unit, build and browser tests |
| `requirements.txt` / `.lock` | −2 direct and −9 locked packages | Clean venv: `pip check` and 259 tests |

**Kept deliberately:**
- `db.create_job` and `db.set_retrieval_config` (used by DB tests).
- The legacy `deleting` status (recovery path and MCP views).
- Chat's `sendingRef` (prevents the input from re-enabling early).
- Retrieval diagnostics `fusion` and `dense_ranks` (consumed by the retrieval benchmark).

---

# Previous audit (11–12 November 2026)

- Replaced the deletion status transition, multiple commits and compensating writes with one database operation. Job deletion and failed-index cleanup share the collection naming and deletion SQL. The foreign key handles job-owned transcript chunks.
- Removed the unused vector retriever wrapper. The production retrieval path continues to use dense search, BM25, reciprocal rank fusion, and FlashRank.
- Removed three unreachable React components and their cursor styling, stale sample environment flags, and an unused font request. Consolidated responsive result rules and reused parsed findings and completed results.
- The dependency change was limited to two Python pins. Existing FastAPI, React/Vite, PostgreSQL/pgvector, LiteLLM and Workers entry points continue to provide the app's functionality. Browser and benchmark fixtures remain test-only.
