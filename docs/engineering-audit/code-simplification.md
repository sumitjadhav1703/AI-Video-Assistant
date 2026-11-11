# Code simplification

- Replaced the deletion status transition, multiple commits and compensating writes with one database operation. Job deletion and failed-index cleanup share the collection naming and deletion SQL. The foreign key handles job-owned transcript chunks.
- Removed the unused vector retriever wrapper. The production retrieval path continues to use dense search, BM25, reciprocal rank fusion, and FlashRank.
- Removed three unreachable React components and their cursor styling, stale sample environment flags, and an unused font request. Consolidated responsive result rules and reused parsed findings and completed results.
- The dependency change was limited to two Python pins. Existing FastAPI, React/Vite, PostgreSQL/pgvector, LiteLLM and Workers entry points continue to provide the app's functionality. Browser and benchmark fixtures remain test-only.
