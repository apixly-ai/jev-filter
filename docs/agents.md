# Connect your agent

[简体中文](agents.zh-CN.md)

Jev Filter is a CLI and Python library. A shell-capable agent can use it immediately;
no MCP server or extra autonomous agent is required. The key design rule is:
**collect → judge → compact packet inside the program**.

Prefer the [typed JavaScript client or scoped read-only MCP](integrations.md) when
your host needs those interfaces. They preserve partial results and evidence without
duplicating inference. `eval` checks saved probabilities offline; per-question policy
and versioned contracts keep routing decisions inspectable.

## Install the portable skill

After the [npm installation](getting-started.md), choose your agent:

| Agent | Skill directory | Instruction file |
|---|---|---|
| Codex | `~/.codex/skills/jev-filter/` | Project `AGENTS.md` |
| Claude Code | `~/.claude/skills/jev-filter/` | Project `CLAUDE.md` |
| Another harness | Its supported skill directory | Its system/tool instructions |

```sh
# Codex; use ~/.claude/skills for Claude Code.
mkdir -p ~/.codex/skills
cp -R "$(npm root -g)/@apixly/jev-filter/skills/jev-filter" ~/.codex/skills/
```

If a directory already exists, review and merge your local customizations first.
From a repository checkout, the same skill is `skills/jev-filter/`. Restart or reload
skills if your harness requires it. Verify with `jev-filter doctor` in the environment
where the agent executes commands, not only your interactive terminal.

## Paste this routing guidance

```text
Use jev-filter for many records that need repetitive semantic judgment
against clear criteria. Prefer native tools for exact IDs, paths, selectors,
calculations, short outputs and latency-sensitive steps.

Give Jev the goal, scope, exclusions, success criteria and sourced facts.
Shared facts belong in context; record-specific history belongs on the record.
Declare required_context and required_record_fields. Missing facts require
REVIEW/NEEDS_CONTEXT, not a guess.

Keep collection, analysis and compact output inside one tool call.
Do not first load all raw output into the main conversation. Do not wrap
an existing Jev-backed workflow again. Inspect unresolved IDs and source
receipts only when needed. Typed judgments do not authorize actions.

Use automatic batching and up to 30 independent requests; no result cache.
For a new semantic workflow, measure quality, failures, whole-operation
latency, returned context and actual per-model usage with a paired baseline.
```

## The context handoff

| Caller supplies | Example | Why it matters |
|---|---|---|
| Goal and scope | “Current checkout request, project Beta” | Stops matching the wrong record |
| Known facts with references | `{ "deployment": "r17", "source": "deployment manifest" }` | Separates observation from assumption |
| Exclusions | “Ignore failures followed by current success” | Preserves the user's actual condition |
| Success criteria | “Unique enabled export in JSON format” | Defines when selection can finish |
| Record history | Current + previous attempt on that request | Prevents cross-record context leakage |
| Expected output | Selected IDs, review IDs, typed answers | Avoids unnecessary generated summaries |

Use the [copyable collector recipe](recipes.md#1-custom-command-output) as your first
integration. The [context contract](context-contract.md) explains each field.

## Handle the packet

1. Parse stdout even when the process exits **2**: partial results are useful.
2. Use `selected_ids`; hold `review_ids` for inspection. `complete=false` needs attention.
3. Read an original with `jev-filter read ARCHIVE_PATH --id SOURCE_ID`.
4. Keep identity, freshness, authorization, idempotency and execution verification in
   your existing program. Jev does not replace these controls.

Wait on a genuinely running process rather than rerunning the command. Commands may
have side effects even if their output is missing. Do not retry uncertain collectors.

## Python workflows

Keep Python if your existing program already uses it. Install `.[code]` or a release
wheel. This typed adapter packs compatible requests and restores original IDs:

```python
from jev_filter.batch import run

result = run([
    {
        "id": "request-17",
        "request": {
            "model": "jev-1.13.0",
            "state": {"signal": "DNS resolution still fails before connection."},
            "questions": {
                "route": {
                    "type": "choice",
                    "instructions": "Classify only the observed signal.",
                    "criteria": {
                        "NETWORK": "DNS, TCP or TLS establishment failure",
                        "OTHER": "A different established failure",
                        "REVIEW": "Insufficient evidence"
                    }
                }
            }
        }
    }
], workers="auto")

for row in result["results"]:
    if not row["ok"]:
        continue  # retain for your existing review/failure path
    print(row["id"], row["answers"]["route"]["choice"])
```

For language-independent integration, pass the same JSON array to
`jev-filter batch --input -`. The collector keeps raw state internal and receives
only typed results/usage. An existing workflow should call this adapter once per
batch, not launch a process per record. [First-user acceptance](benchmarks.md#first-user-integration-acceptance).
