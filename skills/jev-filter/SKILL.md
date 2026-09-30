---
name: jev-filter
description: Use Jev Filter for program-owned semantic filtering, candidate selection, code search and grouped log triage when many records need clear typed judgments, and for hosted execution of short, verifiable browser or desktop goals and surveys over many records. Prefer native tools for exact or short tasks; not a replacement for open-ended reasoning or action authorization.
---

# Jev Filter

Requires an installed `jev-filter` CLI and the user's TypeSafe credentials. Use
`jev-filter doctor` for local readiness; `--live` is explicitly billable.

- Choose `code-search` for symbol-expanded source candidates, `locate` for an
  observed Camofox target, `triage` for correlated JSON/JSONL events, and `exec` or
  `query` for a custom collector. Use `--help` for exact flags.
- Keep collection and analysis in one program segment. Do not first read the whole
  raw output into the main model and then call a redundant classifier.
- Provide the precise goal, intended scope, confirmed facts with sources and success
  criteria. Declare necessary context fields. Shared policy belongs in `context`;
  object-specific history stays with that record. Never fill missing facts by guessing.
- Use positive atomic requirements for compound logic, or Choice for mutually
  exclusive intents. Questions, thresholds and output schema are caller-controlled.
- Allow automatic batching/connection reuse, up to 30 independent requests. No result
  cache. Dependent browser actions stay ordered.
- Consume complete typed results without reclassifying every settled row. Inspect
  only unresolved originals. Do not retry an uncertain external command.
- Preserve scope, source freshness, identity and authorization checks. A selected
  target is not proof of an executed action. The locator does not click.
- `browse` / `desktop` execute a short goal themselves: supply named values
  (`--value key=value`), a verifier (`--verify-text` / `--verify-url`) and stay the
  planner. Treat `needs_confirmation`, `needs_value`, `blocked` (challenge,
  login_required) and `unverified` as your turn: ask the user before passing a
  `--confirm` token or `--allow-irreversible`. Never supply passwords.
- `survey` answers typed questions over many records and aggregates in code; write the
  narrative yourself from its report and cite record IDs. Check `calibrated` before
  trusting confidence floors.
- New semantic integrations need an A/B with fixed inputs, quality, failures, complete
  operation time and actual usage. Keep negative results; do not promise universal
  cost or latency improvement.

See [contract and examples](references/contract.md) for input/output details.
