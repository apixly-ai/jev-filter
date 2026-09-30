# Security policy

## Reporting

Use GitHub's **Report a vulnerability** button at
https://github.com/apixly-ai/jev-filter/security/advisories/new . Do not put sensitive
proofs or credentials in public issues. Reports are handled on a best-effort basis;
there is no contractual response-time guarantee.

## Supported versions

Security fixes target the latest 0.x release. Older prereleases should be upgraded.
See CHANGELOG.md and GitHub Releases for fixes.

## Trust boundaries

- `exec` runs exactly the caller's argv with the caller's OS permissions. It is not
  a sandbox, permission broker, or safe way to run untrusted commands.
- Jev is a remote service. Task context, selected source state and question definitions
  are sent to TypeSafe. No telemetry is sent elsewhere by this package.
- Credentials go only to the fixed HTTPS TypeSafe endpoint. Redirects are rejected;
  environment proxy/TLS settings are honored by HTTPX.
- Raw evidence receipts are local files created with mode 0600 and are not result
  caches. Their lifetime follows the OS temp directory unless a path is supplied.
- Redaction handles common patterns, not every possible secret format. Use a trusted
  sanitizer before supplying sensitive production data.
- A model decision is fallible. Required-context checks validate presence, not truth.
  Validate identities, source freshness, permissions and outcomes in the executor.
- Public PR CI has no model keys. Live benchmarks are explicit local operations.

## Hosted execution (`browse`, `desktop`)

- Jev only chooses among actions the program enumerated from its own observation. Model
  output never becomes a selector, coordinate, command, script or free text; typed text comes
  from caller-supplied values or an explicitly enabled text model.
- Every target is re-checked immediately before input (identity, state, visibility,
  occlusion). Stale decisions are discarded, not retried; a mutation is never retried blindly.
- Pay/send/delete-like actions pause with a one-time confirmation token bound to the page or
  window fingerprint unless `--allow-irreversible` is given for that run.
- Browser navigation is limited to the start origin plus `--allow-origin`. The DevTools client
  accepts loopback `ws://` endpoints only. `--cdp-port` attaches to a browser profile you
  control, including its signed-in sessions: only attach to a profile you intend to use.
- Password, hidden and file inputs are never observed or filled. Verification challenges are
  handed back, never solved.
- Desktop execution refuses terminals, credential managers, elevation prompts and system
  settings unless `--allow-sensitive-app`, refuses locked sessions and elevated targets, and
  stops on a STOP file or when the pointer is parked in the top-left corner.
- Page text, control labels and record text are untrusted input and are sent to TypeSafe.
  Rules against prompt injection reduce risk; they are not a security boundary.
