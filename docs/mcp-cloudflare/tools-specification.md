# Tools specification

The four tools return a single MCP text item containing JSON. The JSON text is capped at 24 KiB in UTF-8. Per-video tools accept an opaque UUID alias in the `job_id` field. Keep the alias and any `next_cursor` as returned and pass them back unchanged. Video timestamps describe the stored record. Transcript timing is approximate where available. Stored text may contain instructions and should be treated as data by the client.

| Tool | Arguments | Result |
| --- | --- | --- |
| `list_videos` | Optional `limit` and `cursor`. Defaults to 5 and permits 1–10. | `items` and `next_cursor`. Items contain `job_id`, `status`, `created_at`, and `title`. |
| `get_job_status` | Required `job_id`. | `job_id`, `status`, `step`, and `error`. The `error` field is `null` or a safe message with code `PROCESSING_FAILED` or `PROCESSING_INTERRUPTED`. |
| `get_video_summary` | Required `job_id`. | `job_id`, `title`, `summary`, `action_items`, `key_decisions`, `open_questions`, and `truncated_fields`. |
| `get_transcript` | Required `job_id`, optional `limit` and `cursor`. Defaults to 4 and permits 1–6. | `job_id`, `chunks`, and `next_cursor`. Each chunk contains `ordinal`, `text`, `start_ms`, `end_ms`, and `timing_precision`. |

Video listing orders by creation time and alias, both descending. Creation times are UTC with microsecond precision. Transcript pagination uses the ordinal within the selected video, with its cursor bound to the alias. A `null` cursor marks the last page. Video titles are capped at 200 characters, summary text at 1,500, each structured summary group at 750, and each transcript chunk at 500. The views clip fields before the Worker serializes them. The Worker returns `TEMPORARY_UNAVAILABLE` if the serialized text exceeds the total byte budget.

Legacy records return eligible metadata. Titles, summaries, and transcript excerpts require content approval, the `done` state, and `hybrid-v1` retrieval data. A share can expose status and creation time with content approval disabled. Chunk timing fields can be `null`. Hidden, deleting, and absent aliases return `NOT_FOUND`. Queued and running content returns `NOT_READY`. Other records without eligible content return `CONTENT_UNAVAILABLE`. Tool errors set `isError` and return a JSON `error` object with a stable `code` and safe `message`. The tool error codes are `INVALID_INPUT`, `NOT_FOUND`, `NOT_READY`, `CONTENT_UNAVAILABLE`, and `TEMPORARY_UNAVAILABLE`. Authentication and rate limiting occur at the HTTP boundary before tool execution.
