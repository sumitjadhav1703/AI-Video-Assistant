# Testing report

## Audit 2 — 13 November 2026

All runs were local: macOS arm64, Python 3.11.15, Node 24.14.0. Disposable pgvector (`pgvector/pgvector:pg16`) ran in Colima Docker on loopback. Provider HTTP was mocked throughout. No test used Neon, Render, Vercel, Cloudflare or a live provider.

| Suite | Command | Before | After |
| --- | --- | --- | --- |
| Backend, offline | `PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m unittest discover -s tests` | 242 OK, 39 skipped | **259 OK**, 40 skipped (DB) |
| Backend + disposable pgvector | same, with `TEST_DATABASE_URL` set | 242 OK, 0 skipped | **259 OK**, 0 skipped |
| Backend inside the Linux image | `docker run … python -m unittest discover -s tests` | not run | **OK** |
| Backend in a clean venv from the trimmed lock | same | — | **259 OK**, `pip check` clean, `import langchain` fails as intended |
| Frontend unit | `cd web && npm test` | 8 pass | **15 pass** (parse tests and api tests added) |
| Frontend build | `npm run build` | pass | **pass** |
| Browser: sample page | `node web/tests/sample.browser.mjs` (Playwright 1.63.0) | — | **pass** |
| Browser: live session (intercepted API) | `node web/tests/live-session.browser.mjs` | **fail** (pre-existing locator bug T1) | **pass** |
| E2E: real backend, mocked providers | `tests/browser/backend_fixture.py` + `tests/browser/journey.mjs` against a production Vite build | — | **pass** (details below) |
| MCP typecheck + dry-run bundle | `npm run typecheck`, `npm run build` | pass | **pass** |
| MCP permissions (Postgres) | `node --test tests/permissions.test.ts` | — | **1 pass** |
| MCP Worker live (`wrangler dev` + fixtures) | CI recipe, local | — | **3 pass**, 1 skipped by design |
| Release-script tests | `node --test scripts/release_vercel.test.mjs tests/test_release_worker.mjs` | — | **8 pass** |
| 512 MiB / 0.1 CPU workload gate | `python -m scripts.benchmark_recruiter_demo … --linux-gate` | **FAIL** | **PASS** (see performance) |

**End-to-end journey details.**
- Covered: upload of a 2 s clip; an injected polling transport failure that was recovered; results; summary and findings; a cited chat answer; authenticated deletion (200).
- Timing: results in 6.6 s and chat in 1.1 s, against a backend pipeline time of 2.2 s.
- After deletion, the database held 0 jobs, 0 chunks, 0 vector collections, 0 embeddings and 0 held slots. Usage counters were retained by design.

**Regression tests added:**
- `tests/test_audit_regressions.py`: guardrails, chunk tail, timestamp clamp, chat cap, and attempt pruning (DB).
- Route recovery and blank-finding fallback, in `test_gateway.py`.
- Trivial and partial quotes, and the whole-chunk quote, in `test_rag_evidence.py`.
- Upload admission order, 409 result, question byte limit, docs and CORS, in `test_api_limits.py`.
- `web/src/lib/parse.test.js`, plus 3 new `api.test.js` cases.

**Tests changed to match corrected behaviour:**
- `test_empty_upload_releases_slot_and_marks_failed` asserted the quota-burning order. It is now `…_is_rejected_before_admission`.
- The Meta test asserted a single reservation for 4 requests.
- Evidence fixtures used 2-word quotes.
- Tests that called the removed wrapper functions now call the live entry points.

**Not run:**
- Live provider calls (not authorized).
- Hosted Render, Vercel, Neon and Cloudflare checks (no deployment authorized).
- Native AMD64 workload: the local machine is arm64. CI runs it on `ubuntu-24.04` AMD64.
- Hinglish/Sarvam end to end (requires a live provider; covered by unit tests with mocked HTTP).
- The real-YouTube download path (disabled in the API).

**Test-isolation note:** without `PYTHON_DOTENV_DISABLED=1`, `test_sarvam_piece_quota_denial_does_not_send_extra_audio` fails, because a local `.env` adds a Groq fallback profile. CLAUDE.md already requires the variable, and CI sets it.

---

# Previous audit (11–12 November 2026)

## Executed checks

| Check | Evidence |
| --- | --- |
| Python dependency install and consistency | Clean audit virtual environment from 117 locked wheels. `uv pip check` passed. |
| Backend regression and integration | 191 passed, 0 failed, 0 skipped in 6.632 s. Includes disposable PostgreSQL 16.15, real pgvector 0.8.1, pinned FlashRank, and intercepted Gemini-to-Groq fallback. |
| Frontend unit tests | 7 passed, 0 failed, 0 skipped. Tests cover errors, Retry-After, authentication headers, malformed successful payloads, and redirect handling. |
| Frontend production build | Passed with Vite 6.4.5 and 38 transformed modules. JS 171.10 kB, 55.63 kB gzip. CSS 3.90 kB, 1.44 kB gzip. |
| Chromium UI regression | Passed. At 320 px the page width stayed 320 px and the Ask button right edge was 283 px. Transcript disclosure, offline sample navigation, and ready-session resume passed. |
| Chromium-to-API integration | Passed. A synthetic 120-second clip went through real FFmpeg, PostgreSQL, pgvector, and FlashRank with intercepted provider HTTP. Browser assertions cover acknowledgement, progress, recovery from a failed poll, result, timestamped chat evidence, and deletion. Final run reached results in 6.536 s and chat in 1.633 s, with three status attempts including the injected failure. PostgreSQL retained seven text-provider attempts and one audio attempt, with zero job, chunk, collection and embedding rows. |
| MCP unit and integration | All four test definitions passed across independent local runs. Real PostgreSQL verified shared views, grants, canonical alias and cursor handling. Local Wrangler verified authenticated legacy and modern HTTP, request limits, read-only tools, pagination and `429`. A separate database-outage run returned a safe tool error. |
| MCP build and type check | Passed with Wrangler 4.160.0. Dry-run bundle 1,440.11 KiB, 256.27 KiB gzip. |
| Dependency and secret scans | Final successful advisory scans reported zero known Python/npm findings. Redacted working-tree, local Git history and frontend scans confirmed no exposed credentials. |
| Docker build and startup | ARM64 and AMD64 images built and started as UID 65532. Both initialized pgvector and served `/health` on a custom port. |
| Linux workload | ARM64 strict gate passed. Rosetta AMD64 strict gate failed at title generation. AMD64 one-CPU diagnostic completed all jobs. See the [measurements](performance-and-optimization.md#linux-cgroup-v2-release-test). |
| Syntax and configuration | `git diff --check`, JavaScript syntax, cleanup and Render YAML parsing, and the Linux recipe's shell syntax passed. |

The database-delete rollback, malformed cleanup auth, sensitive validation input, and incomplete cleanup regressions reproduced failures before the fixes. An early backend integration attempt also caught a missing copied model fixture and a SQL-mock whitespace expectation. The fixture was restored and the test expectation was aligned with the same parameterized SQL.

## Reproduce

Run the Python suite from the repository root with `python -m unittest discover -s tests -v` and a disposable loopback `TEST_DATABASE_URL`. Supply the local pgvector SQL and library via `PGVECTOR_TEST_SQL_PATH` and `TESTPGVECTORLIB` for the real pgvector case. The asset verifier requires the pinned FlashRank files. Run `npm test` and `npm run build` in `web/`. Use the disposable fixture procedure for [MCP integration](../mcp-cloudflare/testing-plan.md).

For Chromium integration, create a disposable loopback database named `ava_audit_browser`. Start `python -m tests.browser.backend_fixture` with `AVA_BROWSER_TEST_DSN` and, if needed, the two local pgvector fixture variables. Build the frontend with `VITE_BACKEND_URL=http://127.0.0.1:55800`, then run `npm run preview -- --host 127.0.0.1 --port 55173 --strictPort` from `web/`. Run `node tests/browser/journey.mjs` from the repository root with `AVA_BROWSER_MEDIA` set to a synthetic clip. Use a local Playwright package and Chromium, with optional `PLAYWRIGHT_MODULE` and `AVA_CHROMIUM_EXECUTABLE` overrides.

## Checks pending

Native AMD64 workload, image OS-package vulnerability scan, hosted integration, and live provider inference were **NOT RUN**. See [deployment readiness](deployment-readiness.md) and [remaining issues](remaining-issues.md).

## Backend test inventory

All entries passed in the final PostgreSQL run.

<details>
<summary>test_api_limits (40)</summary>

- `APILimitTests.test_authentication_and_invitation_before_parsing_or_preflight` — PASS
- `APILimitTests.test_chat_rate_limit_is_429_with_retry_after` — PASS
- `APILimitTests.test_chat_redacts_question_and_returns_citations` — PASS
- `APILimitTests.test_chat_releases_exact_slot_after_provider_failure` — PASS
- `APILimitTests.test_chunked_body_cap_before_json_parsing` — PASS
- `APILimitTests.test_cleanup_does_not_report_success_when_a_database_delete_failed` — PASS
- `APILimitTests.test_consent_required_before_job_admission` — PASS
- `APILimitTests.test_database_failure_is_safe_and_no_provider_runs` — PASS
- `APILimitTests.test_default_mode_is_sample` — PASS
- `APILimitTests.test_delete_database_failure_has_safe_response` — PASS
- `APILimitTests.test_disabled_processing_rejects_before_body_read` — PASS
- `APILimitTests.test_duplicate_files_rejected_without_reservation` — PASS
- `APILimitTests.test_empty_upload_releases_slot_and_marks_failed` — PASS
- `APILimitTests.test_hinglish_is_rejected_before_admission` — PASS
- `APILimitTests.test_invalid_question_rejected_before_provider_or_reservation` — PASS
- `APILimitTests.test_job_budget_exhaustion_has_no_retry_after` — PASS
- `APILimitTests.test_job_token_is_bound_and_expires` — PASS
- `APILimitTests.test_legacy_result_redacts_transcript` — PASS
- `APILimitTests.test_local_path_and_invalid_language_rejected_before_admission` — PASS
- `APILimitTests.test_multipart_overflow_closes_parser_tempfiles` — PASS
- `APILimitTests.test_no_untrusted_forwarded_ip_used` — PASS
- `APILimitTests.test_non_ascii_cleanup_credentials_are_unauthorized` — PASS
- `APILimitTests.test_ordinary_job_cannot_be_elevated` — PASS
- `APILimitTests.test_owner_admission_rejects_non_synthetic_input_and_ambiguous_paid_opt_in` — PASS
- `APILimitTests.test_owner_credentials_and_global_switch_fail_closed` — PASS
- `APILimitTests.test_owner_job_artifacts_require_both_credentials_and_chat_keeps_same_budget` — PASS
- `APILimitTests.test_padded_question_uses_trimmed_length` — PASS
- `APILimitTests.test_quota_returns_retry_after` — PASS
- `APILimitTests.test_rejects_active_delete` — PASS
- `APILimitTests.test_status_poll_uses_narrow_query` — PASS
- `APILimitTests.test_total_body_length_cap_before_parsing` — PASS
- `APILimitTests.test_unconfigured_pipeline_rejected_before_job_body_or_admission` — PASS
- `APILimitTests.test_validation_omits_chat_input_but_identifies_invalid_field` — PASS
- `CLIOwnerTests.test_owner_cli_uses_same_budget_and_rejects_arbitrary_questions` — PASS
- `JobSafetyTests.test_disabled_worker_makes_no_media_calls_and_releases_reservation` — PASS
- `JobSafetyTests.test_failed_rag_removes_partial_vectors` — PASS
- `JobSafetyTests.test_failure_update_error_retains_slot_for_recovery` — PASS
- `JobSafetyTests.test_media_validation_is_actionable_and_provider_errors_are_generic` — PASS
- `JobSafetyTests.test_owner_worker_uses_synthetic_text_without_media_or_transcription` — PASS
- `JobSafetyTests.test_processing_budget_rejects_after_transcription_before_generation_or_indexing` — PASS

</details>

<details>
<summary>test_audio_budget (9)</summary>

- `AudioBudgetDatabaseTests.test_reservations_survive_connections_and_job_deletion` — PASS
- `AudioBudgetTests.test_cli_preflight_rejects_unapproved_profile_before_admission` — PASS
- `AudioBudgetTests.test_failed_provider_call_keeps_prior_reservation` — PASS
- `AudioBudgetTests.test_groq_redirect_is_not_followed_and_configured_host_is_fixed` — PASS
- `AudioBudgetTests.test_profile_must_be_explicit_verified_and_bounded` — PASS
- `AudioBudgetTests.test_quota_denial_prevents_provider_call` — PASS
- `AudioBudgetTests.test_sarvam_piece_quota_denial_does_not_send_extra_audio` — PASS
- `AudioBudgetTests.test_sarvam_refuses_redirect_response_without_forwarding_key` — PASS
- `TimestampBoundaryTests.test_submillisecond_out_of_bounds_and_reverse_times_are_rejected` — PASS

</details>

<details>
<summary>test_audio_processor (16)</summary>

- `AudioSafetyTests.test_blank_download_size_uses_default` — PASS
- `AudioSafetyTests.test_blank_duration_setting_uses_default` — PASS
- `AudioSafetyTests.test_download_directory_removed_when_processing_fails` — PASS
- `AudioSafetyTests.test_download_failure_removes_private_directory` — PASS
- `AudioSafetyTests.test_download_size_hook_cleans_partial_file` — PASS
- `AudioSafetyTests.test_enabled_youtube_validates_host_and_rejects_playlists` — PASS
- `AudioSafetyTests.test_invalid_durations_are_rejected_before_conversion` — PASS
- `AudioSafetyTests.test_invalid_media_has_safe_validation_error` — PASS
- `AudioSafetyTests.test_missing_ffmpeg_removes_chunk_directory` — PASS
- `AudioSafetyTests.test_subprocesses_are_bounded_and_local_only` — PASS
- `AudioSafetyTests.test_timeout_removes_chunk_directory` — PASS
- `AudioSafetyTests.test_uploaded_manifest_cannot_read_a_sibling_audio_file` — PASS
- `AudioSafetyTests.test_youtube_challenge_offers_upload_without_using_cookies` — PASS
- `AudioSafetyTests.test_youtube_disabled_and_invalid_urls_never_download` — PASS
- `AudioSafetyTests.test_youtube_metadata_rejects_live_and_overlong_before_download` — PASS
- `AudioSafetyTests.test_youtube_rejects_redirects_and_uses_single_video_extractor` — PASS

</details>

<details>
<summary>test_benchmark_retrieval (2)</summary>

- `BenchmarkTests.test_metrics_are_bounded_and_use_relevant_ranks` — PASS
- `BenchmarkTests.test_recruiter_benchmark_reads_cgroup_limits_and_counters` — PASS

</details>

<details>
<summary>test_db_limits (14)</summary>

- `DatabaseLimitTests.test_active_job_cannot_be_deleted_or_cleanup_selected` — PASS
- `DatabaseLimitTests.test_chat_and_delete_cannot_both_win` — PASS
- `DatabaseLimitTests.test_chat_ip_minute_day_and_global_limits` — PASS
- `DatabaseLimitTests.test_chat_limits_and_active_chat_delete_are_atomic` — PASS
- `DatabaseLimitTests.test_cleanup_uses_terminal_update_time` — PASS
- `DatabaseLimitTests.test_daily_limits_survive_job_deletion` — PASS
- `DatabaseLimitTests.test_failed_api_delete_rolls_back_artifacts_and_can_be_retried` — PASS
- `DatabaseLimitTests.test_failed_job_insert_rolls_back_quota_and_slot` — PASS
- `DatabaseLimitTests.test_global_limit_applies_across_ips` — PASS
- `DatabaseLimitTests.test_old_buckets_pruned_without_resetting_current_usage` — PASS
- `DatabaseLimitTests.test_parallel_admission_has_one_winner` — PASS
- `DatabaseLimitTests.test_positive_api_upload_result_chat_delete_preserves_usage` — PASS
- `DatabaseLimitTests.test_utc_buckets_come_from_database_clock` — PASS
- `DatabaseLimitTests.test_wrong_owner_cannot_release_slot` — PASS

</details>

<details>
<summary>test_gateway (35)</summary>

- `GatewayTests.test_all_quota_denials_preserve_shortest_retry_after` — PASS
- `GatewayTests.test_attempt_metadata_records_success_and_retains_usage_reservation` — PASS
- `GatewayTests.test_attempt_reserved_before_provider_and_response_is_sanitized` — PASS
- `GatewayTests.test_budget_denial_makes_no_network_attempt` — PASS
- `GatewayTests.test_compatible_transports_use_fixed_routes_with_one_wire_request` — PASS
- `GatewayTests.test_debug_logging_fails_closed_for_private_content` — PASS
- `GatewayTests.test_extraction_combines_findings_in_one_model_request` — PASS
- `GatewayTests.test_fallback_only_transient_and_never_silently_strong` — PASS
- `GatewayTests.test_groq_refuses_invalid_configuration_before_reserving` — PASS
- `GatewayTests.test_groq_rejects_openai_custom_headers` — PASS
- `GatewayTests.test_invalid_structured_output_is_rejected_without_retry` — PASS
- `GatewayTests.test_invocation_requires_operation_scope_before_network` — PASS
- `GatewayTests.test_no_routes_fails_closed` — PASS
- `GatewayTests.test_nvidia_rejects_non_allowlisted_model_before_reservation` — PASS
- `GatewayTests.test_operation_scope_resets_after_exit` — PASS
- `GatewayTests.test_over_budget_recording_preflight_makes_no_generation_or_embedding_call` — PASS
- `GatewayTests.test_paid_meta_requires_decimal_strings_before_reserving` — PASS
- `GatewayTests.test_pipeline_preflight_forecasts_all_attempts_plus_one_chat` — PASS
- `GatewayTests.test_plain_lcel_chain_with_no_handlers_still_works` — PASS
- `GatewayTests.test_rag_preflight_missing_model_or_ranker_precedes_dense_embedding` — PASS
- `GatewayTests.test_real_litellm_router_adapter_uses_exact_gemini_route_without_http_retries` — PASS
- `GatewayTests.test_refusal_metadata_is_rejected_without_fallback` — PASS
- `GatewayTests.test_request_options_and_callback_handlers_cannot_bypass_review` — PASS
- `GatewayTests.test_reservation_time_reduces_network_timeout` — PASS
- `GatewayTests.test_retrieval_preserves_budget_exception_identity` — PASS
- `GatewayTests.test_route_order_and_owner_permissions_are_checked_again_on_invoke` — PASS
- `GatewayTests.test_route_quota_or_local_context_denial_skips_without_dispatch` — PASS
- `GatewayTests.test_route_rejects_paid_unknown_and_duplicate_routes` — PASS
- `GatewayTests.test_safe_selected_route_metadata_and_usage_are_preserved` — PASS
- `GatewayTests.test_shared_provider_rejects_invalid_other_operation_limits` — PASS
- `GatewayTests.test_shared_provider_uses_lowest_generation_and_embedding_ceiling` — PASS
- `GatewayTests.test_structured_summary_title_and_findings_preserve_public_text` — PASS
- `GatewayTests.test_task_output_limits_are_reserved_and_cannot_be_unbounded` — PASS
- `GatewayTests.test_text_sanitized_before_dispatch_and_before_reuse` — PASS
- `GatewayTests.test_tracing_configuration_fails_before_provider` — PASS

</details>

<details>
<summary>test_guardrails (8)</summary>

- `GuardrailsTests.test_authorization_basic_and_bearer_values_are_redacted` — PASS
- `GuardrailsTests.test_common_tokens_and_benign_numbers` — PASS
- `GuardrailsTests.test_credential_formats_preserve_offsets_and_hide_complete_values` — PASS
- `GuardrailsTests.test_cross_segment_card_and_phone` — PASS
- `GuardrailsTests.test_cross_segment_pii_is_redacted_before_chunking` — PASS
- `GuardrailsTests.test_job_persists_only_sanitized_transcript_and_chunks` — PASS
- `GuardrailsTests.test_sensitive_data_and_benign_details` — PASS
- `GuardrailsTests.test_standalone_configured_provider_key_formats_are_redacted` — PASS

</details>

<details>
<summary>test_hybrid (11)</summary>

- `HybridTests.test_corrupt_raw_corpus_is_sanitized_and_empty_reranker_is_unavailable` — PASS
- `HybridTests.test_embedding_query_redacts_before_http_and_records_failure_without_retry` — PASS
- `HybridTests.test_embedding_vector_is_finite_normalized_and_dimension_checked` — PASS
- `HybridTests.test_foreign_dense_id_fails_before_reranking` — PASS
- `HybridTests.test_hydration_uses_owned_text_and_required_reranker` — PASS
- `HybridTests.test_missing_local_model_fails_without_download` — PASS
- `HybridTests.test_real_local_reranker_reuses_session_and_restores_full_text` — PASS
- `HybridTests.test_reranker_rejects_unbounded_candidate_batches_before_model_load` — PASS
- `HybridTests.test_rrf_deduplicates_and_ties_by_ordinal` — PASS
- `HybridTests.test_sparse_excludes_no_overlap_and_normalizes_unicode` — PASS
- `HybridTests.test_sparse_retains_matching_terms_with_negative_bm25_idf` — PASS

</details>

<details>
<summary>test_pgvector_integration (1)</summary>

- `RealPGVectorTests.test_real_persistence_search_filter_mixed_dimensions_and_cleanup` — PASS

</details>

<details>
<summary>test_prepare_reranker (3)</summary>

- `PrepareRerankerTests.test_bad_archive_hash_and_traversal_are_rejected` — PASS
- `PrepareRerankerTests.test_file_hash_failure_does_not_install` — PASS
- `PrepareRerankerTests.test_verified_archive_prepares_only_manifest_files` — PASS

</details>

<details>
<summary>test_provider_budget_db (9)</summary>

- `ProviderBudgetDatabaseTests.test_context_rejection_never_reserves_and_ambiguous_failure_is_not_refunded` — PASS
- `ProviderBudgetDatabaseTests.test_cooldown_and_forecast_choose_healthy_alternative` — PASS
- `ProviderBudgetDatabaseTests.test_forecast_checks_each_mandatory_route_cooldown` — PASS
- `ProviderBudgetDatabaseTests.test_forecast_counts_planned_usage_before_using_fallback` — PASS
- `ProviderBudgetDatabaseTests.test_paid_cap_is_atomic_and_survives_job_deletion` — PASS
- `ProviderBudgetDatabaseTests.test_paid_job_and_daily_dollar_caps` — PASS
- `ProviderBudgetDatabaseTests.test_paid_missing_or_underpriced_pricing_never_reserves` — PASS
- `ProviderBudgetDatabaseTests.test_parallel_last_operation_attempt_is_reserved_once` — PASS
- `ProviderBudgetDatabaseTests.test_provider_rejection_rolls_back_and_job_deletion_preserves_usage` — PASS

</details>

<details>
<summary>test_provider_guards (10)</summary>

- `ProviderGuardsTests.test_delete_collection_is_noop_when_table_absent` — PASS
- `ProviderGuardsTests.test_delete_collection_requires_no_provider_and_uses_parameterized_name` — PASS
- `ProviderGuardsTests.test_disabled_guard_covers_all_provider_factories` — PASS
- `ProviderGuardsTests.test_embeddings_are_bounded_without_hidden_retries` — PASS
- `ProviderGuardsTests.test_exact_transcript_boundary_is_accepted` — PASS
- `ProviderGuardsTests.test_groq_client_is_bounded_and_model_resolved_at_call` — PASS
- `ProviderGuardsTests.test_oversized_context_rejected_before_model_or_embedding` — PASS
- `ProviderGuardsTests.test_sarvam_key_and_model_resolved_at_call` — PASS
- `ProviderGuardsTests.test_transcript_length_is_rejected_without_truncation` — PASS
- `ProviderGuardsTests.test_unverified_stt_never_reserves_or_constructs_a_remote_client` — PASS

</details>

<details>
<summary>test_rag_evidence (5)</summary>

- `EvidenceTests.test_empty_context_abstains_without_invoking_generation` — PASS
- `EvidenceTests.test_unknown_ids_and_fabricated_quotes_abstain` — PASS
- `EvidenceTests.test_valid_evidence_restores_server_timestamps` — PASS
- `EvidenceTests.test_whitespace_answer_abstains_even_with_a_valid_quote` — PASS
- `EvidenceTests.test_whitespace_quote_abstains_without_returning_draft` — PASS

</details>

<details>
<summary>test_recovery (12)</summary>

- `InterruptedAPITests.test_interrupted_job_has_actionable_status_and_no_result` — PASS
- `InterruptedAPITests.test_upload_keeps_slot_if_terminal_job_write_fails` — PASS
- `InterruptedAPITests.test_upload_metrics_use_copied_bytes_and_exclude_content_and_identifiers` — PASS
- `RecoveryTests.test_chat_recovery_preserves_done_job_and_quotas` — PASS
- `RecoveryTests.test_cli_defaults_to_inspection_and_requires_worker_shutdown_acknowledgment` — PASS
- `RecoveryTests.test_competing_recovery_cannot_clear_a_replacement_token` — PASS
- `RecoveryTests.test_finish_job_rejects_a_completed_job` — PASS
- `RecoveryTests.test_recent_processing_progress_blocks_recovery_even_with_old_slot` — PASS
- `RecoveryTests.test_recover_processing_preserves_stage_usage_and_other_slot` — PASS
- `RecoveryTests.test_schema_upgrade_ages_existing_slot_conservatively_and_once` — PASS
- `RecoveryTests.test_worker_preserves_published_index_when_finish_acknowledgment_is_lost` — PASS
- `RecoveryTests.test_worker_removes_partial_index_after_confirming_failure` — PASS

</details>

<details>
<summary>test_storage (3)</summary>

- `StorageTests.test_chunk_cascade_isolation_and_immutable_model` — PASS
- `StorageTests.test_legacy_is_retained_and_cannot_be_silently_switched` — PASS
- `StorageTests.test_partial_timestamps_reject_whole_corpus_without_switching_model` — PASS

</details>

<details>
<summary>test_telemetry (3)</summary>

- `TelemetryTests.test_media_sizes_are_local_and_cleanup_logs_no_path` — PASS
- `TelemetryTests.test_retrieval_and_transcription_do_not_log_private_content` — PASS
- `TelemetryTests.test_stage_failure_logs_no_exception_and_logging_failure_is_ignored` — PASS

</details>

<details>
<summary>test_timestamps (3)</summary>

- `TimestampsTests.test_offsets_use_real_wav_duration_and_bad_timestamps_fail` — PASS
- `TimestampsTests.test_real_wav_duration_and_empty_transcript` — PASS
- `TimestampsTests.test_sarvam_piece_has_coarse_bounds` — PASS

</details>

<details>
<summary>test_usage_limits (6)</summary>

- `UsageSettingsTests.test_defaults_and_blank_values_are_safe` — PASS
- `UsageSettingsTests.test_guardrail_module_exists` — PASS
- `UsageSettingsTests.test_identity_is_normalized_hmac_without_ip_disclosure` — PASS
- `UsageSettingsTests.test_invalid_limits_do_not_disable_safety` — PASS
- `UsageSettingsTests.test_provider_enabled_requires_secret` — PASS
- `UsageSettingsTests.test_provider_guard_disabled_and_sarvam_fail_closed` — PASS

</details>

<details>
<summary>test_vector_cleanup (1)</summary>

- `VectorCleanupTests.test_delete_cascades_only_to_matching_job_and_handles_absence` — PASS

</details>
