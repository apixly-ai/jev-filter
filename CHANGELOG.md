# Changelog

The format follows Keep a Changelog; versions follow SemVer within the limitations
of a 0.x API (minor releases may make documented breaking changes).

## [0.3.0] - 2026-09-30

### Added
- Hosted execution: Jev Filter now executes, not only filters. Jev chooses among actions the
  program enumerated; the program acts, re-checks every target first and verifies results.
- `browse`: web goals over a standard-library DevTools client (private headless Chrome/Edge/
  Chromium, or `--cdp-port` to attach) or a local Camofox server. One request per step asks the
  operation and a target per operation (design adapted from browser-use/jev-ultrafast, MIT).
  Named values (`--value`), optional text model (`--text-model`), origin limits, dialog handling,
  `--verify-text/--verify-url/--verify-question`, `--dry-run`, and pause/resume for irreversible
  actions with a one-time `confirm_token` (`--keep-open`, `--cdp-port`/`--target-id`, `--confirm`).
- `extract`: structures a page into header-labelled table rows, blocks and links, then applies the
  `query` contract.
- `desktop`: the same loop in one Windows (UI Automation) or macOS (Accessibility) application,
  with an OCR fallback (Windows.Media.Ocr, Vision) for drawn UI and `--list` for windows.
  Deterministic safety gates refuse terminals, credential managers and system settings, locked
  sessions and elevated targets, and stop on a STOP file or pointer in the top-left corner.
- `survey`: typed questions over JSONL/CSV/JSON/text inputs with optional screening, packed
  concurrent evaluation, code-side aggregation (distributions, crosstabs, examples, uncertain and
  failed IDs), pre-flight budgets (`--max-usd`, `--max-requests`), `--labels` calibration and
  optional category proposal from a fixed-seed sample.
- `doctor` reports hosted-execution readiness. `pip install 'jev-filter[desktop]'` adds the
  desktop backends.
- Benchmarks: `python -m benchmarks.hosted --live` with synthetic browser, desktop and survey
  fixtures and program-checked outcomes; results in `benchmarks/results/2026-09-30-hosted.json`.

### Fixed
- Camofox is reached on `127.0.0.1` instead of `localhost`, removing a ~2 s IPv6 fallback per
  request on Windows (`locate` tutorial 5059 ms -> 1192 ms). Benchmark tab cleanup sends `userId`
  in the DELETE body as Camofox 2.4.8 requires.

### Scope
- Hosted execution is a short-step executor with an observable outcome; open-web long tasks
  belong to a planning agent. macOS was exercised with a fake accessibility tree and on CI runners
  when Accessibility can be granted, not on a physical Mac.

## [0.2.4] - 2026-09-24

### Fixed
- `--input -` and JSON output are read and written as UTF-8 regardless of the console codepage; on Windows (GBK) piped records previously failed with `JSONDecodeError`.
- npm publication waits up to ~15 minutes per package for the registry to finish asynchronous processing (previously ~4 minutes, which aborted the 0.2.3 publication after each platform bundle); the workflow timeout is raised to 90 minutes accordingly.

## [0.2.3] - 2026-09-24

### Fixed
- The Python package runs natively on Windows: `pool` no longer imports the POSIX-only `resource` module, key files are read without `O_NOFOLLOW`/`getuid` (symlinks still rejected; Unix mode checks are POSIX-only), and `exec` drains pipes with reader threads and kills the command tree with `taskkill /T` where `select()` and `killpg` are unavailable.
- The dashboard no longer sets `SO_REUSEADDR` on Windows, where it let a second instance bind a busy port instead of raising `EADDRINUSE`; busy-port fallback and `PortInUse` now behave the same on every platform.
- All text files (dashboard template, locator script, `--input` JSON, stats config/exports) are read and written as UTF-8 explicitly instead of the process locale, which is not UTF-8 on Windows by default.
- CI runs the test suite on `windows-latest` in addition to Linux and macOS.
- Docs: native Windows installation points at the GitHub Release wheel or a git source install; there is no PyPI package.

## [0.2.2] - 2026-09-23

### Added
- The dashboard opens its authenticated localhost URL in the default browser on startup. Use `--no-open` in headless environments.
- Browser launch failures retain the running server and printable URL; browser launch runs separately from HTTP serving.
- Publication waits for npm asynchronous processing and package-index visibility before fresh installation, without repeating uploads.

## [0.2.1] - 2026-09-23

### Fixed
- Dashboard startup automatically chooses a free loopback port if the default 8765 is occupied.
- Explicit busy ports return an actionable `PortInUse` error; `--port 0` selects an available port. Invalid port values are rejected before binding.
- Dashboard instances never share a listening port, including on Python versions with reusable-port defaults.

## [0.2.0] - 2026-09-23

### Added
- Opt-in, private SQLite usage ledger for CLI collection/filtering and typed-batch costs.
- Per-call input-token reduction and USD input-value estimates, Jev cost, price snapshots and explicit unknown/negative results.
- Local byte estimates, optional tiktoken text counts and opt-in official OpenAI/Anthropic counters.
- Read-only localhost dashboard with model/date/method filters, daily/tool breakdowns and filtered JSON/self-contained HTML exports.
- Isolated arithmetic, privacy, failure, API-adapter, concurrent-write and rendered desktop/mobile tests.

### Scope
- Statistics estimate normalized candidate JSON versus the returned packet once; they do not claim whole-agent or subscription invoice savings.
- No change to semantic predicates, inference planning, authorization or result-cache policy.

## [0.1.0] - 2026-09-22

### Added
- Portable packaged CLI and Python API with no private workspace dependencies.
- Context admission, typed selection/filtering, scoped evidence and failure retention.
- Code-search, browser locator, grouped JSON/JSONL triage, and caller-command wrapper.
- HTTPX connection reuse, bounded retries, up to 30 workers and no result cache.
- Optional Python-packaged JS/TS/Go grammar support; Python AST support is built in.
- English/Chinese documentation, agent skill, reproducible benchmarks and release CI.

[0.1.0]: https://github.com/JIA-ss/jev-filter/releases

- Native npm distribution for macOS and Linux x64/ARM64, including interpreter, parsers and pinned ripgrep.
- Visual bilingual README, data-derived charts, runnable recipes and agent integration instructions.
- Repository moved to Apixly; immutable release tags and restricted workflow permissions.
