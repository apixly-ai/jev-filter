# Contract quick reference

```sh
jev-filter query --input records.json --task 'Find relevant records' --analysis spec.json
jev-filter exec --task 'Find relevant failures' --analysis spec.json -- python collect.py
jev-filter read /path/from/archive --id source-id
```

Input records are `{id,text,...metadata}`. Common metadata becomes `source.*` in
questions/projections. `context` carries caller facts; `required_context` and
`required_record_fields` declare necessary paths. Null/empty missing values produce
NEEDS_CONTEXT/REVIEW, not a guessed result. Presence checks do not establish truth.

`requirements: [{id,statement,expected}]` compiles independent positive predicates.
A known mismatch excludes; otherwise unknown means review; otherwise match.
`questions` alternatively supports native Choice/Noul/Score schemas. `choose` selects
from the complete observed candidate set, including NONE and REVIEW.

Read stdout even on exit 2: it can contain successful IDs alongside unresolved IDs.
Use `selected_ids`, `review_ids`, `complete`, and receipt references. Default output
is compact; exact originals and full answer distributions remain local. Never upload
private receipts or keys as part of a public bug report.

`browse`, `desktop`, `extract` and `survey` inputs and outputs are in [hosted.md](hosted.md).
