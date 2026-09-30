# CLI reference

[简体中文](cli.zh-CN.md)

Use `jev-filter --help` and `<command> --help` for exact flags.

| Command | Purpose |
|---|---|
| `query --input FILE --task TEXT` | Judge supplied `{id,text,...metadata}` records |
| `exec --task TEXT -- COMMAND ARGS` | Capture a trusted command internally, then judge |
| `search PATTERN --root PATH --task TEXT` | rg candidate retrieval with adjacent context |
| `code-search PATTERN --root PATH --task TEXT` | Expand candidate hits to complete code symbols |
| `locate --session S --tab T --origin URL --task TEXT` | Read-only Camofox control selection and freshness guard |
| `triage --input FILE --task TEXT` | Group JSON/JSONL events by request ID, then judge |
| `batch --input FILE` | Native typed request contracts, packed when compatible |
| `read ARCHIVE --id ID` / `list ARCHIVE` | Recover retained input without inference |
| `doctor [--live]` | Local setup checks; optional billable live check |

## Analysis modes

`--mode choose` evaluates a complete candidate set with NONE/REVIEW options. More
than 253 candidates or excessive context requires narrowing. `filter` retains
multiple matches. `analyze` exposes caller-defined typed answers. `passthrough`
returns evidence without inference. `auto` skips inference for <=1200 characters
only when no custom analysis was supplied; it does not infer task semantics.

`--analysis FILE` controls context, required fields, questions/atomic requirements,
filtering, ranking and output projection. `--workers auto` uses independent request
count, OS resources and the cap of 30. `--batch-size auto` packs by complete request
size and question count. `--budget-chars` limits displayed text, not the complete
selected/review ID sets. `--plan` collects once and plans without inference—it is
not a dry-run of the collector command.

## Execution and output

Exit 0: completed operation (including explicit passthrough). Exit 2: partial or
unresolved decision/collection; still parse stdout. Exit 1: invalid input/setup or
unhandled failure. Exit 130: interrupted. `exec` does not invoke a shell implicitly;
use explicit `sh -c` only for a trusted pipeline. Commands run once; timeout/overflow
terminates their process group. No command retry is automatic.

The normal output retains `selected_ids`, `review_ids`, `complete`, source identities,
private receipt references and known usage. `ok` means execution status, not truth.
A required context failure reports `NEEDS_CONTEXT` before collection. `--diagnostics`
includes more metadata and should be used only when appropriate for the input.

`exec --split auto` accepts a records JSON array, otherwise paragraph blocks. Other
modes are `json`, `whole`, `paragraphs`, `lines`; use lines only for self-contained
records. `--accept-exit 0 1` admits an expected no-match exit from rg.

## Specialized collectors

Code search parses Python plus optional JS/JSX/TS/TSX/Go grammars without executing
source. Unsupported/invalid code stays reviewable. Contained spans are deduplicated;
changed file revisions are rejected before returning a match. It is a lexical
shortlist, not exhaustive semantic indexing.

The locator uses an existing local Camofox-compatible server on 127.0.0.1:9377 and
an explicitly named session/tab/origin. It observes reachable controls, omits input
values, strips URL credentials/query/fragment, and verifies the selected Node before
returning a selector. Duplicate indistinguishable controls, stale nodes and ambiguous
scopes require review. It never clicks, types or navigates. Reverify after changes.

Triage preserves per-correlation event order and duplicate counts, redacts common
credential patterns, and leaves malformed records visible. Prefer atomic requirements
for compound inclusion/exclusion. It does not establish live recovery or root cause.
