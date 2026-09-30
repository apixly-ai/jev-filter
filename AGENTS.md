# Contributor and agent instructions

This project is a portable Python package. Use a virtual environment and install
`.[code,dev]`. Never rely on a maintainer's home directory, private skills, browser
profiles, customer records or local credentials.

- Write a failing behavioral test before changing runtime behavior.
- Keep deterministic collection, context admission, semantic inference, and action
  verification separate. Model selection is not permission or proof of execution.
- Never add result caching, raw-evidence stdout, or concurrency above 30 without an
  explicit reviewed design change. Hosted execution (`jev_context.act`) may only execute
  actions the program enumerated from its own observation; model output must never become
  a selector, coordinate, command, script or unvetted text. Keep freshness guards, the
  irreversible-action gate, origin limits and desktop safety gates intact.
- Preserve partial failures and unknown usage; never bill unknown failures as zero.
- Run Ruff, pytest with coverage, package build, offline benchmark and public-content
  checks before a PR. Run optional browser tests when DOM logic changes, and the Windows
  desktop tests (`-m desktop`, `.[desktop]`) when desktop backends change.
- For semantic/planner changes, attach a reproducible A/B: fixed synthetic inputs,
  expected results, baseline and treatment, failures, context bytes, actual model
  usage and whole-operation timing. State negative results and scope limitations.
- Live tests are opt-in and billable. Use only synthetic/permitted inputs and an
  explicitly supplied test credential. Never run them in untrusted PR CI.
- Keep English/Chinese README claims synchronized. Do not turn historical prototype
  results into promises for the released package.
