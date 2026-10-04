# Reproduce a read-only skill route

This fixed synthetic fixture compares the released native CLI with the optional
skill helper. Both run the same Jev filtering core; it tests routing and preservation
of unresolved records, not model improvement or whole-agent speed.

Use a virtual environment with `.[code,dev]`, an installed Jev Filter 0.4.1 CLI and
an explicitly authorized synthetic-test credential. Prepare two local input files:

```sh
python - <<'PY'
import json
from pathlib import Path
fixture = json.loads(Path('examples/skill-workflow/fixture.json').read_text())
Path('/tmp/skill-records.json').write_text(json.dumps(fixture['records']))
Path('/tmp/skill-analysis.json').write_text(json.dumps(fixture['analysis']))
PY
```

Each of the following makes one billable API request for the seven admitted records.
The eighth record lacks provenance and is retained for review without inference.
Repeat twice, reversing arm order for the second pair, with no result cache:

```sh
jev-filter query --input /tmp/skill-records.json \
  --task 'Select current connection-establishment failures before HTTP headers; retain missing facts for review' \
  --analysis /tmp/skill-analysis.json --workers 2 --budget-chars 4000 \
  --mode filter --diagnostics

python skills/jev-filter/scripts/workflow.py records \
  --input /tmp/skill-records.json \
  --task 'Select current connection-establishment failures before HTTP headers; retain missing facts for review' \
  --analysis /tmp/skill-analysis.json --workers 2 --budget-chars 4000
```

Expected in both arms: `selected_ids=[r1,r2,r3]`, `review_ids=[r6,r7]`,
`complete=false`, exit **2**. Missing current facts and provenance do not become
accepted evidence. Preserve both successful IDs and review IDs, source receipts,
whole-process timing, UTF-8 output bytes and telemetry even when incomplete.

The [recorded four-run result](../../benchmarks/results/2026-10-04-live-skill-workflow.json)
matched all expected dispositions: native median **1,351 ms**, helper **1,260 ms**,
both returning **3,458 UTF-8 bytes**. Four requests reported **12,288 input** and
**2,620 output tokens** with no unknown usage. The input-only estimate is
**$0.000516096** using the dated 2026-10-04 $0.042/million input-token rate from
[TypeSafe](https://docs.typesafe.ai/models); actual invoiced cost is unavailable.

Two repetitions are a smoke sample. The wrapper simply replaces its process with
one canonical CLI invocation; this timing difference does not establish a speed
gain. No primary continuation, customer action or production workflow is measured.
The requested model is `jev-1.13.0`; the adapter does not separately expose a
provider-resolved model identity. Original input/rule/helper hashes are recorded.
