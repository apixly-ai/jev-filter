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
- `browse` / `desktop` execute a short goal themselves. Build each call from one
  observable goal with its constraints, named values (`--value key=value`, or a
  `--values` JSON object whose entries may be `{"value", "description", "sensitive"}`)
  and at least one verifier (`--verify-text`, `--verify-url`). Stay the planner for
  anything longer and call once per sub-goal. `--dry-run` shows the next step only.
- Only `status: done` (exit 0) is success. `needs_confirmation` (`pending`,
  `confirm_token`), `needs_value` (`field`/`fields`), `blocked` (`challenge`,
  `login_required`) and `unverified` are your turn: ask the user before passing
  `--confirm` or `--allow-irreversible`. Never supply passwords.
- `extract` turns a page into `row`/`heading`/`block`/`link` records, then follows the
  `query` contract.
- `survey` takes records (JSONL/JSON/CSV/directory) and a spec: `task`, 1..16 typed
  `questions`, optional `screen`, `group_by`, `keep`, `confidence_floor`. Run
  `--dry-run` for the cost estimate first. It aggregates in code; write the narrative
  yourself from the report and cite record IDs. Check `calibrated` (pass `--labels`)
  before trusting confidence floors.
- New semantic integrations need an A/B with fixed inputs, quality, failures, complete
  operation time and actual usage. Keep negative results; do not promise universal
  cost or latency improvement.

- [references/contract.md](references/contract.md): records, analysis specs and the
  `query`/`exec`/`extract` output.
- [references/hosted.md](references/hosted.md): `browse`/`desktop`/`extract`/`survey`
  flags, values files, survey specs, labels, output packets and what to do per status.
