# Install, run, read the result

[简体中文](getting-started.zh-CN.md)

## Recommended: npm CLI

Node.js 22+ on macOS or Linux; Windows users can use WSL or install the Python package natively (see [Python library / source install](#python-library-source-install); there is no PyPI package).
The platform package includes the Python runtime and code parsers.

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
```

Pin a version with `npm install -g @apixly/jev-filter@0.4.0`.
For a project-local dependency, use `npm install @apixly/jev-filter` and invoke
`npx jev-filter`. Avoid `--omit=optional`: the correct platform binary is an optional
dependency. Installation does not run a postinstall script or configure your agent.

GitHub release fallback (the same npm package):

```sh
npm install -g https://github.com/apixly-ai/jev-filter/releases/download/v0.4.0/apixly-jev-filter-0.4.0.tgz
```

## Configure your key

```sh
export TYPESAFE_API_KEY='your-key'
jev-filter doctor --live
```

`doctor` alone is offline; `--live` makes one small billable request. To avoid storing
a key in shell history, use an existing owner-only file instead:

```sh
export TYPESAFE_API_KEY_FILE="$HOME/.config/jev-filter/api-key"
# Create the file using your preferred secret manager/editor; set mode 0600.
```

For compatibility with earlier local installs, the implicit default remains
`$XDG_CONFIG_HOME/jev-context/api-key` or `~/.config/jev-context/api-key`.
The explicit `TYPESAFE_API_KEY_FILE` setting above selects the new directory. The file must be a regular file owned by you, mode
0600 (a symlink is rejected). Never put the key in Git or agent prompts.

## Try one complete example

This works outside a checkout:

```sh
jev-filter query --input - --mode choose \
  --task 'Choose the CURRENT unresolved DNS failure' <<'JSON'
[
  {"id":"a","text":"DNS recovered; requests now succeed."},
  {"id":"b","text":"DNS lookup still fails before connection."}
]
JSON
```

Expected: selected `b`, no review IDs. Add `--plan` for an offline plan.
See [recipes](recipes.md) for command capture, contextual selection, code search,
browser controls and correlated logs. Small examples teach usage, not economic benefit.

## Read the result

| Field | What to do |
|---|---|
| `selected_ids` | Consume matching records for this judgment |
| `review_ids` | Inspect incomplete/uncertain evidence |
| `complete` | `false` means the decision or scope still needs attention |
| `archive` | Local original records, readable by ID |
| `receipt` | Local judgments/diagnostics |
| `telemetry.usage` | Known input/output tokens; check `usage_complete` |

```sh
jev-filter list ARCHIVE_PATH
jev-filter read ARCHIVE_PATH --id SOURCE_ID
```

Replace the placeholders with the archive path and record ID returned by your call.
Files are private (0600) and are evidence storage, not inference caches.

| Exit code | Meaning |
|---|---|
| `0` | Complete result or explicit passthrough |
| `2` | Partial/review result—still parse stdout |
| `1` | Invalid input, setup or execution failure |
| `130` | Interrupted |

Do not automatically rerun a collector after a failed or interrupted call. It may
already have executed. [Full CLI contract](cli.md).

## Python library / source install

Use this if you embed Jev in an existing Python workflow. Requires Python 3.10+;
install ripgrep separately for source-based search.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install 'jev-filter[code] @ git+https://github.com/apixly-ai/jev-filter.git@v0.4.0'
```

The wheel in GitHub Releases is also supported. No PyPI publication is assumed.
[Python integration example](agents.md#python-workflows).

## Troubleshooting

- **Command not found:** reopen your shell and ensure npm's global bin directory is on PATH.
- **Missing platform package:** reinstall without `--omit=optional`; verify OS/architecture support.
- **Credentials not configured:** check the environment in the agent's tool process.
- **No search results / rg missing:** check `doctor`, ignore rules and lexical query; source installs need ripgrep.
- **Exit 2:** inspect `review_ids`, missing context and collection scope; it is not an empty success.
- **An exact task became slower:** use the native tool; adding semantic inference is not always beneficial.
