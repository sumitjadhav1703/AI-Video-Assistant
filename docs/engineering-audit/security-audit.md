# Security audit

## Credential handling

- Before copying the working snapshot, a redacted pattern scan covered its 73 non-ignored untracked files. The audit also scanned 18 reachable local Git commits and 62 distinct blobs, the current working tree, and all four built Vite artifacts.
- No real secret was confirmed in those inputs. The two initial review matches were the benchmark's disposable DSN guard and the synthetic browser-fixture token. The scan covered provider token shapes, common service tokens, private-key headers, credentialed connection strings, and long secret assignments. It cannot detect every credential format or establish that remote refs and prior clones contain the same history.
- The application keeps job capabilities in authorization headers. API errors omit raw validation input and internal database errors. The built frontend exposes its configured public API URL. Backend and Worker credentials belong in server bindings or local ignored configuration.

## Access, abuse and media

- Job reads, chat and deletion require a job-scoped capability. Owner operations also require the distinct owner credential. Tests cover cross-job attempts, expiry, malformed authorization, inactive jobs, durable limits, and concurrent writes.
- Admin cleanup uses a distinct token. Malformed bytes fail safely. Cleanup no longer signals success after an unexpected delete failure. The workflow uses HTTPS and empty GitHub token permissions.
- FFmpeg probe and decode use media-only demuxers and restricted protocols. Multipart body limits, file caps, duration checks, temp-file cleanup, and DB reservations have local regression coverage. FFmpeg still handles untrusted binary media. The Linux image smoke tests verified the unprivileged runtime UID.
- YouTube is a gated CLI path. Canonical URLs and extractor selection close the generic redirect entry point. Groq and Sarvam transcription requests reject redirects. Live YouTube behavior, proxy attribution and hosted edge protections remain unverified.
- MCP uses a separate bearer secret and a least-privilege view reader. Disposable PostgreSQL checks exercised real grants, shared-record filtering, content approval, and role isolation. Wrangler local tests covered origin rejection, authentication, body caps and rate limiting.
- Redaction is pattern-based. Use of synthetic or public non-personal media remains part of the demo policy.

## Dependencies

| Manifest | Result |
| --- | --- |
| Python lock | 117 pins. Initial `pip-audit` found 13 filelock advisories. Targeted updates from filelock 3.32.7 to 4.2.1 and LiteLLM 1.108.0 to 1.108.5 cleared the known findings on rescan. |
| Frontend lock | npm audit found zero advisories across 116 dependency entries. |
| MCP lock | npm audit found zero advisories across 211 dependency entries. A later repeat hit DNS failure. The lock was unchanged. |
| Docker OS packages | Linux images built. OS-package vulnerability scanning remains pending. |

LiteLLM's updated macOS wheel was inspected for startup hooks before import. Its package initializer and native extension matched the prior pin. The locked pair was exercised with intercepted provider HTTP. Advisory and wheel checks have limited supply-chain coverage. [LiteLLM 1.108.5 LTS](https://github.com/BerriAI/litellm/releases/tag/v1.108.5).

The filelock findings were CVE-2026-112907, CVE-2026-112908, CVE-2026-112909, CVE-2026-112910, CVE-2026-112911, CVE-2026-112912, CVE-2026-112913, CVE-2026-112915, CVE-2026-112935, CVE-2026-112936, CVE-2026-112938, CVE-2026-112939, and CVE-2026-112940.
