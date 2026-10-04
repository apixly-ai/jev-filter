# Benchmarks

[简体中文](benchmarks.zh-CN.md)

## Fresh paid evidence · 2026-10-04

**91.6–97.2% less returned tool context, with the original evidence still recoverable.**
This is the new whole-operation result: **24 real primary-agent runs**, three fixed
synthetic scenarios (`code-search`, `triage`, `exec`), two primary models
(`gpt-5.6-luna`, `gpt-6-astra`), raw/filtered arms and two repetitions per cell.
Filtering completed **12/12** operations, raw context **11/12**; all **24/24**
selected the exact expected ID sets. The raw Astra triage arm selected correctly
but one run failed the full expected response contract; it remains in the denominator.

### Whole operations: context is the win, latency is mixed

| Primary model / scenario | Tool context less | Mean time raw → filtered | Cold API-equivalent change | Completion raw / filtered |
|---|---:|---:|---:|---:|
| Luna / code-search | 96.1% | 14.87 → 16.12 s | −14.2% | 2/2 / 2/2 |
| Luna / triage | 97.2% | 15.21 → 17.09 s | −3.1% | 2/2 / 2/2 |
| Luna / exec | 91.6% | 15.82 → 15.84 s | **+1.1%** | 2/2 / 2/2 |
| Astra / code-search | 96.1% | 18.51 → 19.44 s | −22.0% | 2/2 / 2/2 |
| Astra / triage | 97.2% | 23.12 → 19.58 s | −23.2% | 1/2 / 2/2 |
| Astra / exec | 91.6% | 18.73 → 22.19 s | −4.8% | 2/2 / 2/2 |

Five of six cells were slower by **0.1–18.4%**. Only Astra triage was faster
(**15.3%**), and its raw arm contains the failed response contract. Two repetitions
are a smoke comparison, not a statistical latency study. Fixture setup is excluded
and recorded separately; collection, Jev inference, real primary-agent shell tool
use and continuation are timed together. Tool-context bytes count what the tool
returns, not the entire model prompt. Main input includes the harness and the
agent's fixed instructions.

Actual token totals, summed over each model's six raw or six filtered runs:

| Primary model / arm | Main input / cached subset / output | Jev input / output |
|---|---:|---:|
| Luna / raw | 242,638 / 112,896 / 1,804 | 0 / 0 |
| Luna / filtered | 199,220 / 109,824 / 1,478 | 145,014 / 25,086 |
| Astra / raw | 277,875 / 111,360 / 925 | 0 / 0 |
| Astra / filtered | 227,990 / 144,640 / 891 | 145,014 / 25,086 |

Provider usage is complete for these runs. Codex CLI uses configured account
access: **actual subscription billing is unknown**. Cold estimates treat main input
as uncached; cache-adjusted estimates use the observed cached subset. Neither is an
invoice. Luna `exec` becomes **12.0% more expensive** under the cache-adjusted model;
Astra `exec` has unusually more cached input in the filtered arm, so its **70.6%**
adjusted reduction should not be attributed solely to filtering. Pricing is a dated,
caller-supplied [2026-10-04 rate snapshot](../benchmarks/results/2026-10-04-operations-rates.json).
Missing usage or unavailable billing remains `null`, never a zero-cost success.

[Per-run JSON](../benchmarks/results/2026-10-04-live-operations.json) ·
[Summary and exact arithmetic](../benchmarks/results/2026-10-04-live-operations-summary.json) ·
[CSV](../benchmarks/results/2026-10-04-live-operations.csv) ·
[Driver](../benchmarks/operations.py)

![Fresh whole-operation context, equivalent cost and latency](assets/operations-live.png)

### Batching: a faster Jev stage, with a smaller input bill

The [fresh native batching test](../benchmarks/results/2026-10-04-live-batching.json)
uses 96 fixed synthetic records × two predicates, four arms and three repetitions.
All **12/12** operations returned the exact expected selection and complete usage.
Single-record parallel uses at most **12** workers; batch-parallel needed two requests
and two workers, while single-record arms made 96 requests per operation.

| Arm | Mean whole filtering time | Input tokens over three repetitions | Exact runs |
|---|---:|---:|---:|
| Single-record serial | 29.50 s | 209,244 | 3/3 |
| Automatic batch, serial | 1.82 s | 91,086 | 3/3 |
| Single-record parallel, cap 12 | 3.22 s | 209,244 | 3/3 |
| Automatic batch + parallel | 1.25 s | 91,086 | 3/3 |

Batching reduces input **56.5%**; batch-parallel is **61.2% faster** than single-record
parallel in this sample. Time includes planning, native inference and reduction, but
**no primary-agent continuation**. This is not a whole-agent speedup. Repeated easy
record templates and network variation limit generalization. Across all arms the
provider reported **600,660 input / 110,964 output tokens**, complete usage and no
unknown attempts. This legacy driver exposes requested `jev-1.13.0`, not observed
response IDs. [Driver](../benchmarks/run.py).

### Record workflows: better selection comes with more work

The [native record A/B](../benchmarks/results/2026-10-04-live-records.json) uses
fixed synthetic code, full Git before/after files and connection-phase records.
It times collection → admission → real native Jev → reduction → source freshness.
There is no primary-agent continuation in this experiment.

| Workflow | Observed quality | Returned bytes / whole-operation trade-off |
|---|---|---|
| Exact code vs opt-in recall, both semantically filtered | **4/12 → 10/12** matches; no false positives in either arm. | **5,284 → 9,706 bytes** total. Median **854 → 849 ms** across six operations per arm; no speed claim. |
| Retain all eight changed files vs semantic diff triage | Four target changes selected in both repetitions; irrelevant selections **8 → 0**, no missed targets. | **11,428 → 8,700 bytes** (23.9% less); median **503 → 1,465 ms**. |
| Separate 18-record calibration and 18-record holdout | Both holdout arms **36/36** expected dispositions over two repetitions, including eight reviews. | Calibration selected threshold **0.0**: **no additional threshold benefit** on this easy sample. Native inference was fresh in each arm. |

The deliberately missing lexical-overlap case is still missed in both code arms.
The current recall implementation broadens lexical/symbol/caller candidates; it is
not exhaustive semantic indexing. Calibration and holdout use distinct records but
similar handwritten scenarios. The threshold selector fits no probability calibrator
and establishes no population guarantee.

This canonical series made **20 native requests**, with **35,250 input / 5,858 output
tokens**, returned model **`jev-1.13.0`**, complete usage and successful freshness checks.
[Fixed inputs and runner](../benchmarks/live_records.py) disclose the gold labels,
policy grid, model usage by operation and the negative results.

### Interfaces: real paid calls through the shipped routes

[All 13 checks passed](../benchmarks/results/2026-10-04-live-interfaces.json): Python
CLI and a **fresh registry installation of npm 0.4.0** each exercised 32-record query,
code recall, eight correlated events and a six-file diff. An independent official
MCP client negotiated **2025-11-25**, called filter/search/triage, and recovered the
exact original plus its SHA-256. Local Chromium extraction selected four in-stock
USB-C lamps; code parsed the source prices and retained the three under $35. CLI
survey classified **64/64** topic labels with exact aggregate counts.

These are synthetic interface checks, not open-world accuracy. The survey repeats
eight simple ticket templates. **16 requests** returned **71,616 input / 17,562 output
tokens**, complete usage. These public interfaces suppress the returned provider
model ID; the result records requested `jev-1.13.0` separately and keeps resolved
identity unavailable. [Runner](../benchmarks/live_interfaces.py) preserves complete
synthetic output packets while replacing machine paths and receipt locations.

### Browser: strict review, a verified fix, and failed experiments

The [final pinned source A/B](../benchmarks/results/2026-10-04-live-browser-final-ab.json)
compares the released 0.4.0 source with the scroll-evidence repair on the same
`jev-1.13.0`, **0.55 top probability / 0.10 margin** policy: eight local fixtures,
three repetitions per arm, independent DOM/storage checks. Expected outcomes are
**15/24 → 18/24**: verified completions **12 → 15** plus **three correct irreversible
stops** in both arms. Wrong actions and false completions are zero in this matrix.

The nested-scroll target changes from **0/3 to 3/3** completed runs. A failed baseline
stops early; the completed treatment needs **6 → 21** model calls and median time
**1.33 → 3.25 s** across these three runs. The existing six-task subset has unchanged
**12/18** expected outcomes: **six ordinary goal runs still need review**. Its known
input grows **2.36%**, request bytes **7.52%**, and median time **3.58%**. The fix keeps
the strict thresholds; it does not make pure Jev finish every goal.

Across the final matrix, baseline/treatment use **171,320 / 202,290 input tokens**
and **12,012 / 12,818 output tokens**, all resolved to `jev-1.13.0` with complete usage.
Browser startup is reported separately; fixture navigation, observation, decisions,
actions and independent final checks are included in the operation timing.

Earlier experiments remain public: [native-select pruning](../benchmarks/results/2026-10-04-live-browser-native-select-ab.json)
reduced expected passes **11/18 → 9/18**; [stronger controls and nested scroll](../benchmarks/results/2026-10-04-live-browser-stronger-cases.json)
showed no pass improvement; [the scroll-evidence trial](../benchmarks/results/2026-10-04-live-browser-scroll-evidence-ab.json)
had **one provider failure with unknown usage**. Its total cost is `null`, not zero.
These failed or incomplete trials are separate from the final complete matrix.

The first [benchmark-only primary-planner recovery](../benchmarks/results/2026-10-04-live-planner-recovery.json)
reached **5/6** expected outcomes. Its independent check rejected one premature Jev
`DONE` after adding the right cart item but before reaching the order gate. **A model's
`DONE` alone is not usable completion.** The negative first matrix stays published.

The [verified continuation reference](../benchmarks/results/2026-10-04-live-planner-recovery-verified.json)
then reached **6/6**: three search completions and three correct `Place order` stops,
under the same strict policy on pinned released 0.4.0. It detects and continues one
premature Jev `DONE`; no wrong actions, accepted false completion claims or main-model
executed tools occurred. The program owns observation and enumerated action IDs,
checks main-planner ID/value-reference output, rechecks freshness, executes guarded
actions and independently verifies the final state. [Reference flow](../benchmarks/live_planner_recovery.py).

This is **reference integration, not a shipped automatic primary-model fallback**.
Whole operation time is **14.7–51.6 s**, median **33.1 s**, including recovery overhead.
The six new runs use `gpt-5.6-luna`: **275,556 input / 70,400 cached-input subset /
1,155 output tokens**, plus actual `jev-1.13.0` **180,522 input / 11,378 output tokens**;
usage is complete, subscription billing unknown. The result also retains the first
matrix's spend separately. Reliable recovery adds work; it does not establish a cheap
or fast universal browser agent.

### Complete audit spend, including failed trials

The [cumulative usage ledger](../benchmarks/results/2026-10-04-live-total-usage.json)
includes pilots, repeated validation and failed experiments, not just the successful
canonical tables: known Jev **2,928,677 input / 324,772 output tokens**, plus **one unknown
provider attempt**. At the stated $0.042/million-input rate, known input corresponds
to a **$0.123004434 estimate lower bound**; cumulative total and actual invoice remain
unknown. Primary-account usage is **1,463,583 input / 563,200 cached subset / 7,315 output
tokens** under subscription access, not a verified API bill. Costs are not silently
zeroed or summed across incompatible billing bases.

### Reproduce a new paid run

Supply a permitted TypeSafe test credential through `TYPESAFE_API_KEY` or
`TYPESAFE_API_KEY_FILE`; do not put it into inputs, reports or source. Model calls
are opt-in and billable. Use new output paths and keep private traces private.

```sh
python -m pip install -e '.[code,dev,docs,browser-test]'
# The independent MCP check also needs the official mcp package.
python -m pip install mcp
python -m benchmarks.run --live --records 96 --repeats 3 --parallel-workers 12 \
  --output local-results/batching-new.json
python -m benchmarks.live_records --live --repeats 2 --output local-results/records-new.json
python -m benchmarks.live_interfaces --live --output local-results/interfaces-new.json
python -m benchmarks.operations --live --models gpt-5.6-luna gpt-6-astra \
  --cases code-search triage exec --repeats 2 --jev-workers 4 \
  --rate-snapshot benchmarks/results/2026-10-04-operations-rates.json \
  --report local-results/operations-new.json --private-dir local-results/operations-traces
```

The workflows above answer different questions: whole-primary-agent context,
record decision quality, and interface correctness. Do not combine their denominators
or turn a local stage improvement into a whole-agent saving.

## Release 0.4 evidence 2026-10-04

These offline checks target the 0.4 program's contracts and interfaces. Contract A/B
uses pinned source baselines; collector recall compares fixed candidate strategies.
They make **zero semantic model calls**. Their scripted responses, labels and program
policies are disclosed. Fresh paid evidence appears above; historical live results follow.

| Scope | Baseline | 0.4 treatment | Tradeoff |
|---|---:|---:|---|
| Scripted decision/accounting behavior | 3/13 expected cases | 13/13 | Review 0 → 6; returned bytes 4,104 → 7,087 |
| False fixture actions | 3 | 0 | Ambiguous operations stop before action |
| Code collector mean recall | 27.8% | 66.7% | Mean precision 66.7% → 47.2%; more context and time |
| Browser observer/action contract | 3/15 | 15/15 | More control state and completed paths increase context/time |
| Freshness rejection checks | 6/6 | 6/6 | Scope, sensitive-value and source guards remain separate |

The decision cases check error/unknown-usage preservation and the application of
supplied probability distributions. They do not measure whether Jev predicted the
right answer. The code collector still misses the fixture with no overlapping
lexical clues; final semantic precision needs its own evaluation. Browser tests run
real local Chromium with a fixed program policy, excluding browser startup; they do
not estimate open-web or Jev-driven success. All per-case failures, context bytes,
timing, source/script hashes and zero actual model usage are retained:
[decisions](../benchmarks/results/2026-10-04-decisions.json),
[retrieval](../benchmarks/results/2026-10-04-retrieval.json),
[browser observation](../benchmarks/results/2026-10-04-browser-observation.json).

The [interface E2E](../benchmarks/results/2026-10-04-release-e2e.json) runs 10 actual
process checks: CLI setup and context admission, collection, stdin triage/redaction,
tracked diff, survey planning, offline evaluation, MCP stdio, the real JS client and
an independent official MCP client (protocol 2025-11-25; four tools; evidence roundtrip).
Inputs are synthetic and commands deliberately plan or require missing context;
zero model requests means this is interface proof rather than semantic quality evidence.

```sh
python -m benchmarks.decision_contracts --output decisions.json
python -m benchmarks.retrieval --repeats 5 --output retrieval.json
python -m benchmarks.browser_observation --repeats 3 --output browser.json
python -m benchmarks.release_e2e --output interfaces.json
# Independent client check: install mcp separately, then add --official-mcp.
jev-filter eval --input examples/evaluation.json --output heldout.json
```

For a new provider comparison, install `.[code,dev,bench-llm]` and the provider's
System One Adapter SDK extra. [The frozen plan](../benchmarks/results/2026-10-04-provider-plan.json)
records 32 input rows, fixed expectations and complete request bytes with no inference.
`python -m benchmarks.providers --live --provider PROVIDER --model MODEL --output X.json`
is explicitly billable and requires supplied test credentials. It measures the filtering
operation, keeps retry-total known usage and unknown failed attempts, and separates
native Jev probabilities from generated LLM probabilities. No fresh provider superiority,
whole-agent speedup or invoice saving is established by the offline release evidence.

See [integration and policy contracts](integrations.md) for defaults, compatibility
and a group-separated held-out evaluation that does not fit a probability calibrator.

## Hosted execution: 2026-09-30

Scope: synthetic local fixtures only, live Jev (`jev-1.13.x`), three repetitions per task. A run
passes only when its final status is the expected one **and** a program check on the final state
holds: URL and storage for the browser, window text for the desktop, generated ground truth for
the survey. The model's DONE is never counted as success. Irreversible fixture actions are
expected to pause (`needs_confirmation`) and are verified not to have happened.

| Line | Transport | Task | Expected | Passed | Median steps | Median requests | Median time | Median input tokens | Jev p50 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| browser | camofox | buy-pauses-before-order | `needs_confirmation` | 3/3 | 8 | 9 | 13.7 s | 26,251 | 358 ms |
| browser | camofox | contact-form-scroll | `done` | 3/3 | 9 | 10 | 7.9 s | 27,401 | 350 ms |
| browser | camofox | delete-is-gated | `needs_confirmation` | 3/3 | 0 | 1 | 0.7 s | 1,709 | 703 ms |
| browser | camofox | search-filter | `done` | 3/3 | 6 | 7 | 9.3 s | 23,594 | 336 ms |
| browser | camofox | shadow-dom | `done` | 3/3 | 1 | 2 | 2.0 s | 3,130 | 504 ms |
| browser | cdp | buy-pauses-before-order | `needs_confirmation` | 3/3 | 8 | 9 | 3.9 s | 26,251 | 349 ms |
| browser | cdp | contact-form-scroll | `done` | 3/3 | 6 | 7 | 3.0 s | 21,188 | 345 ms |
| browser | cdp | delete-is-gated | `needs_confirmation` | 3/3 | 0 | 1 | 0.7 s | 1,709 | 726 ms |
| browser | cdp | same-origin-frame | `done` | 3/3 | 1 | 2 | 1.1 s | 3,294 | 527 ms |
| browser | cdp | search-filter | `done` | 3/3 | 5 | 6 | 2.8 s | 20,405 | 356 ms |
| browser | cdp | shadow-dom | `done` | 3/3 | 1 | 2 | 1.2 s | 3,268 | 568 ms |
| browser | cdp | buy-pauses-before-order (no gated note) | `needs_confirmation` | 3/3 | 8 | 9 | 4.0 s | 25,211 | 359 ms |
| desktop | windows-uia | advanced-tab | `done` | 3/3 | 3 | 4 | 3.4 s | 8,627 | 442 ms |
| desktop | windows-uia | delete-is-gated | `needs_confirmation` | 3/3 | 0 | 1 | 0.8 s | 2,862 | 706 ms |
| desktop | windows-uia | form-save | `done` | 3/3 | 5 | 6 | 5.6 s | 21,215 | 362 ms |
| desktop | windows-uia | ocr-canvas | `done` | 3/3 | 1 | 2 | 2.1 s | 3,569 | 510 ms |

| Variant | Records | Requests | Input tokens | Input USD | Time | Topic | Sentiment | Churn | Screen |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| default | 500 | 19 | 257,075 | $0.0108 | 3.5 s | 100.0% | 94.8% | 100.0% | 98.6% |
| no-screen | 500 | 17 | 234,422 | $0.0098 | 2.1 s | 100.0% | 94.7% | 100.0% | – |
| unpacked | 500 | 940 | 590,522 | $0.0248 | 14.0 s | 100.0% | 95.2% | 100.0% | 98.0% |
| default | 10,000 | 375 | 5,192,517 | $0.2181 | 19.6 s | 100.0% | 95.7% | 100.0% | 98.8% |

[Per-run JSON](../benchmarks/results/2026-09-30-hosted.json)

How to read it:

- **Browser.** The fixture shop has a modal cookie banner, an autocomplete combobox, a native
  select, a results table, a cart with *Place order* and *Remove* buttons, a long form that needs
  scrolling, an open shadow root and a same-origin iframe. Camofox clicks by CSS selector in the
  top document, so the iframe task is not offered there, and every Camofox click spends about
  1.7 s inside Camofox.
- **Ablation.** `no gated note` removes the program's fixed sentence ("irreversible steps are
  gated by the program; keep advancing"). In isolated probes on the results page, goals ending in
  *buy* made Jev choose BLOCKED with probability 0.46–0.60 without it and 0.09–0.13 with it. In
  whole runs the low-confidence-terminal fallback and row-context text also rescue the task, so
  the end-to-end difference is small; the note is kept because it removes the failure at its
  source.
- **Desktop.** A WinForms application (text field, drop-down list, checkbox, tabs, list, a
  *Delete all records* button and a button that opens a modal MessageBox) and a Tk canvas whose
  buttons are drawn pixels, driven through the OCR fallback. Window start-up time is excluded.
- **Survey.** Seeded synthetic support tickets (five topics, three tones, churn mentions, 10%
  spam), English and Chinese. The records are template-generated and easy, so 100% topic accuracy
  here says nothing about your data; measure with `--labels` on a labelled sample. `unpacked`
  sends one record per request (the same questions); `no-screen` skips the relevance pre-pass.
  With only 10% irrelevant records, screening costs more than it saves: it pays off when most
  records are irrelevant.

Reproduce (billable, needs a Chromium; Camofox and the desktop line are optional):

```sh
pip install -e '.[dev,browser-test,desktop]'
python -m benchmarks.hosted --live --lines browser,desktop,survey --repeats 3 \
  --camofox --output /tmp/hosted.json
python -m benchmarks.hosted_report /tmp/hosted.json
```

## Real websites and applications: 2026-09-30

The fixture results above show the mechanics. This read-only audit asks how far the same code
gets on real public websites and real Windows applications. Nothing was bought, posted or signed
in to, and nothing was changed in the code during the audit. Summary data:
[2026-09-30-real-world.json](../benchmarks/results/2026-09-30-real-world.json). The observation
probe is `python -m benchmarks.real_world_coverage`.

Setup: one Windows 11 machine on one network in mainland China, headless Chrome at 1280x900 with a
zh-CN browser language, `jev-1.13.0`. Results depend on region, IP reputation and time, and bot
checks in particular will differ elsewhere.

**Observation coverage.** On 40 public pages, an independent in-page script listed everything a
person could click in the viewport. It then checked which of those the executor's observation
offered. One page failed to launch. Seven were bot checks, error pages or a risk overlay.

| Pages | Clickable elements found | Median page recall | Pooled recall | Pages at 95% or more |
|---|---:|---:|---:|---:|
| 32 content pages | 1,582 | 97.2% | 94.4% | 24/32 |
| of which 25 non-Chinese sites | | 100% | 97.1% | 21/25 |
| of which 7 Chinese sites | | 82.1% | 85.0% | 3/7 |

The misses are mostly clickable elements without a role (58, 51 of them on Chinese sites) and
native inputs made fully transparent under a styled control (23, on 7 sites, for example
Wikipedia's menus). The metric only counts the viewport. Targets below the fold or inside a
scrolled container are a separate gap.

**Live goals.** 24 read-only goals (search, open a page, set a widget) ran twice each, about 12
runs in parallel. "Reached" is a reviewer's judgment from final URLs, titles and archives, not
the verifier's.

| Goal type | Goals | Runs | `done` | Reached | Bot check or sign-in wall | Provider outage | Reached of the rest |
|---|---:|---:|---:|---:|---:|---:|---:|
| Site search | 12 | 24 | 7 | 7 | 8 | 3 | 7/13 |
| Link navigation | 7 | 14 | 4 | 5 | 2 | 1 | 5/11 |
| Widget state | 5 | 10 | 0 | 4 | 0 | 0 | 4/10 |
| **Total** | 24 | 48 | 11 | 16 | 10 | 4 | **16/34 (47%)** |

The 95% interval for 16 of 34 is roughly 31–63%. One `done` was likely false: a DuckDuckGo run
whose URL check also matched the bot-check page. Six runs reached the goal without `done`,
mostly because the verifier sees page text but not widget state.

**Desktop.** Eight Windows applications were observed, and five live goals ran once each; two
passed.

| Application | Toolkit | Controls observed | Live goal | Result |
|---|---|---:|---|---|
| Calculator | WinUI/UWP | 34 | 12 × 34 | passed |
| File Explorer | Shell/XAML | 78 | open a folder | passed |
| Character Map | Win32 | 9 | choose a font | failed: off-screen list items are not offered and there is no scroll action |
| cmake-gui | Qt, no accessibility | 0 (OCR) | open Help | failed: OCR merged the menu bar into one target |
| DB Browser for SQLite | Qt with accessibility | 63 | open Help | failed: Invoke does nothing on Qt menu items; Expand would work |
| Paint | WinUI 3 | 113 | observe only | the canvas is not exposed |
| Beyond Compare | Delphi VCL | 67 | observe only | custom-painted text is invisible |
| Chrome | Chromium | 22 | observe only | page content is hidden unless Chrome runs with `--force-renderer-accessibility` |

**What failed, by goals affected.** A counterfactual check means the change was applied in memory
and replayed. None of these fixes is in 0.3.0.

| Failure | Goals | Checked fix |
|---|---:|---|
| Provider timeouts end the run, and the error code is dropped | 7 | Reruns of the same requests succeeded; a retry for side-effect-free decision requests is untested |
| Localized or non-Cloudflare bot checks and sign-in walls are not recognized (JD's sign-in redirect ends as `origin_blocked`); an invisible reCAPTCHA v3 frame on a normal page is flagged as a challenge | 6 | Untested |
| Role-less clickable elements and transparent native inputs are not offered | 3 (widgets) | MUI and Element Plus succeeded in memory |
| Settle races: DONE before navigation commits, a stale autocomplete list, a self-reloading page that crashes the CLI without a packet | 3 | The crash reproduced; the fixes are untested |
| Targets below the fold or in a scrolled sidebar are never offered | 2 | MDN and Python docs picked the right link in replay |
| The verifier cannot see checked, pressed or selected state | 2 | Scores rose from 0.19–0.33 to 0.67–0.98; one rephrased question scored 0.67–0.73, at the 0.7 pass threshold |
| Link-dense pages exceed the provider's input limit (Hacker News, about 33.6k tokens) | 1 | Removing duplicated row text gave HTTP 200 and the right click |
| Links that open a new tab are not followed | 1 | Untested |

## Historical whole-operation benchmark: 48 agent runs · 2026-09-23

![Whole-operation context, cost and latency results](assets/operations.png)

[Per-run JSON](../benchmarks/results/2026-09-23-operations.json) · [CSV](../benchmarks/results/2026-09-23-operations.csv) · [Aggregates](../benchmarks/results/2026-09-23-operations-summary.json) · [Typed decision evidence](../benchmarks/results/2026-09-23-decisions.json)

This historical 2026-09-23 benchmark tested the public core: **two primary models, four scenarios,
raw/filtered arms and three repetitions = 48 real agent operations**. The primary
agent invoked the same fixed collector exactly once, consumed its output and returned
structured selected IDs. Each model used medium reasoning. Arm order alternated;
each model lane ran serially, with two model lanes active. No Jev result cache was used.

Timing includes the tool call, any Jev inference, the primary model's continuation and
the final browser freshness guard. Browser/page setup is recorded separately and
excluded because the measured locator operation assumes an existing page. This
compares a fixed candidate stream, not unrestricted agents choosing different tools.

Positive cost/latency changes below mean **more expensive/slower**. Context is returned
tool-output characters, not total primary-model tokens.

| Primary model | Scenario | Context reduction | Cold API cost change | Latency change | Raw/filtered complete |
|---|---|---:|---:|---:|---:|
| Astra | code-search | 96.3% | -18.0% | -2.4% | 2/3 → 3/3 |
| Astra | locate | 88.5% | -3.7% | -4.0% | 3/3 → 3/3 |
| Astra | triage | 97.3% | -20.8% | +16.5% | 0/3 → 3/3 |
| Astra | exec | 91.6% | -3.6% | +10.2% | 3/3 → 3/3 |
| Luna | code-search | 96.3% | -10.6% | -4.3% | 3/3 → 3/3 |
| Luna | locate | 88.5% | -2.5% | +43.0% | 3/3 → 3/3 |
| Luna | triage | 97.3% | -2.4% | +27.3% | 3/3 → 3/3 |
| Luna | exec | 91.6% | +0.6% | +3.0% | 3/3 → 3/3 |


**Quality:** all 48 runs selected the expected ID sets, with no observed false additions
or omissions. Four raw Astra runs additionally requested review (one code and three
log runs); all 24 filtered runs finished without review. This is reported separately
from ID correctness. Fewer reviews do not prove better calibration on unseen inputs.
All 48 operations were protocol-valid and reported complete model usage.

**Measurement limits:** two raw command events omitted `aggregated_output` from the
Codex event stream. Their character lengths are null, not zero; no values were imputed.
Context means use the available measurements (2 or 3 per arm). Timing, quality and
usage remain available. Three repetitions per cell are too few for strong statistical
claims. The report includes mean, median, observed min/max and sample counts; it does
not present a noisy p95 as a production guarantee.

**Cost:** estimates use standard, short-context USD rates verified on 2026-09-23:
[Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) input/cached input/output
$10/$1/$50 per million tokens;
[Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) $0.20/$0.02/$1.20;
[Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) $0.042 input and free
output. Both cold and cache-adjusted estimates are retained. Cache-write charges,
regional surcharges, service tiers and discounts are not modeled. These are
**API-equivalent estimates, not the owner's subscription invoice**.

The Luna command scenario was **0.6% more expensive** after adding Jev. Several filtered
scenarios were slower, including Luna browser selection (+43.0%). Use the tool when
context pressure or a measured workload justifies it; do not force it onto cheap,
small or latency-sensitive tasks.

### Absolute values and timing distribution

Each cell uses three runs. Arrows show raw → filtered; times are seconds and costs are API-equivalent USD per operation.

| Model / scenario | Mean time | Median time | Observed range: raw; filtered | Cold API-equivalent cost |
|---|---:|---:|---|---:|
| Astra / code-search | 22.01 → 21.49 | 22.10 → 20.88 | 19.24–24.68; 20.55–23.04 | $0.65282 → $0.53527 |
| Astra / locate | 19.19 → 18.43 | 19.42 → 18.46 | 18.11–20.05; 17.73–19.10 | $0.55392 → $0.53335 |
| Astra / triage | 20.85 → 24.30 | 20.50 → 24.88 | 20.39–21.66; 21.22–26.79 | $0.67587 → $0.53502 |
| Astra / exec | 19.42 → 21.39 | 20.55 → 22.00 | 17.01–20.69; 19.27–22.89 | $0.55358 → $0.53365 |
| Luna / code-search | 21.91 → 20.97 | 21.14 → 20.40 | 18.98–25.60; 17.63–24.87 | $0.01202 → $0.01075 |
| Luna / locate | 17.12 → 24.47 | 17.35 → 17.52 | 16.54–17.46; 16.41–39.49 | $0.01025 → $0.01000 |
| Luna / triage | 20.87 → 26.57 | 20.91 → 19.88 | 19.04–22.66; 19.66–40.17 | $0.01179 → $0.01150 |
| Luna / exec | 19.42 → 20.01 | 18.83 → 20.59 | 17.30–22.12; 16.55–22.87 | $0.01029 → $0.01035 |

The Luna browser mean is affected by one 39.49-second sample. Its filtered median is about 17.52 seconds versus 17.35 raw; the three-run mean is not a stable production latency estimate.

### Reproduce the complete workflow

Requires a compatible Codex CLI authenticated to your own account, Jev credentials,
and a local Camofox server on port 9377 for the browser scenario. The harness creates
only synthetic fixtures and its own browser sessions; it does not click or send messages.

```sh
python -m benchmarks.operations --live \
  --codex "$(command -v codex)" \
  --models gpt-6-astra gpt-5.6-luna --repeats 3 \
  --report local-results/operations.json \
  --private-dir /tmp/jev-filter-operations-unique
```

Use fresh paths. This makes 48 primary-agent calls plus the filtered Jev steps and
consumes account usage. Raw agent events remain private outside the repository;
only allowlisted metrics and synthetic typed answers are exported. The report includes
fixture and runtime hashes. Inputs/gold construction live in
[scenarios.py](../benchmarks/scenarios.py); the full driver is
[operations.py](../benchmarks/operations.py).


## Public package: measured 2026-09-22

[Machine-readable results](../benchmarks/results/2026-09-22-live.json),
[fixture](../benchmarks/fixture.py), [runner](../benchmarks/run.py).

96 synthetic service records, two atomic predicates each, Jev `jev-1.13.0`,
two repetitions per arm with reversed order on repetition two. No result cache.
Wall time includes planning, network, validation and result restoration, but excludes
launching the Python interpreter and downstream primary-agent reasoning.

| Jev execution | Mean seconds | Input tokens, both repetitions | Exact complete runs |
|---|---:|---:|---:|
| Single-record serial | 39.859 | 139,496 | 2/2 |
| Automatic batching, serial | 2.757 | 60,724 | 2/2 |
| Single-record parallel, cap 30 | 3.502 | 139,496 | 2/2 |
| Automatic batching + parallel, cap 30 | 2.368 | 60,724 | 2/2 |

Batching reduced input tokens **56.47%**. Batch + parallel was **32.37% faster than
single-record parallel** and **94.06% faster than single-record serial** in this run.
All runs returned the expected selected IDs with no unresolved records; usage was
reported complete. The result file retains usage, request counts, workers and timings.
These are API-reported tokens, not estimated character counts.

Two runs are a smoke benchmark, not a statistically powered study. Inputs repeat eight
record patterns and are easier than open-world tasks. Network variation is significant;
serial batching was faster than single-record parallel here. A cap of 30 is an upper
bound, not a claim that every request used 30 workers or that 30 is always optimal.


## Historical prototype: primary-agent workflow comparison

Before this standalone package was extracted, a private prototype was tested on
fixed synthetic code-search, browser-control and incident-triage candidates. Two paired
runs used an Astra/medium primary-agent baseline. The following numeric observations
are historical, not measurements of this release. Private full traces are not shipped
because they contain local environment and agent configuration. They therefore have
less public reproducibility than the fresh benchmark above.

| Prototype workflow | Returned context reduction | Cold API-equivalent cost reduction | Total latency change |
|---|---:|---:|---:|
| Code search | 96.13% | 20.58% | **+10.21% slower** |
| Browser control selection | 88.47% | 4.37% | **+4.02% slower** |
| Incident triage | 97.26% | 25.18% | **+1.52% slower** |

Selected IDs matched the expected answers in these fixtures; the raw triage arm also
returned an extra review. The cost figures include the extra Jev step and the primary
model's observed input/output under the historical cold-token price assumptions.
They are API-equivalent estimates, not subscription bills or evidence of money saved
on this particular account. They are not current provider price quotes.


## Reproduce and price your own workload

```sh
python -m pip install -e '.[code,dev]'
python -m benchmarks.run --output local-results/offline-new.json
# Billable; uses configured Jev credentials and never caches results.
python -m benchmarks.run --live --output local-results/live-new.json
```

Each output path must be new so an old or failed run is not overwritten. The offline
mode measures planning only; it is not evidence of model quality or live latency.

For a downstream agent A/B, keep the primary model, reasoning setting, task, candidate
corpus and expected answers fixed. Alternate raw-native and filtered arms; include
collection, Jev, retries, main-agent continuation and any evidence rereads in elapsed
time and usage. Record incomplete/review/failed runs, exact selection or task success,
false omissions, returned context bytes/tokens and input/output tokens **per model**.
A smaller packet alone is not a quality or cost result.

Use your provider's current prices (including cached-input rates where applicable):

```
raw_cost = main_input * main_input_rate + main_output * main_output_rate
filtered_cost = filtered_main_input * main_input_rate
              + filtered_main_output * main_output_rate
              + jev_input * jev_input_rate + jev_output * jev_output_rate
```

Rates must use the same currency and token unit. Include retries and evidence rereads.
If usage is incomplete, label cost as a lower bound. Report both negative and positive
results. Cheap primary models, small inputs, poor context or frequent rereads can erase
the saving. No fixed dollar claim is inferred from the public model-layer benchmark.


## First-user integration acceptance

[Sanitized observations](../benchmarks/results/2026-09-22-migration.json) cover the
maintainer's installed source annotation, Telegram maintenance planning and SRE
routing entrypoints with synthetic data and real Jev calls. All three preserved their
expected decisions and withheld raw input from the compact packet. No message was
sent and no production action was authorized by the test. Existing workflow scripts,
identities and fallback contracts remain private and unchanged.

A separate two-repetition migration A/B used 48 synthetic DNS signals and included
Python process startup: the legacy backend averaged **1.413 s**, the public package
**1.797 s** (**27.2% slower**). Both returned 48/48 correct decisions on each run and
identical usage (6,752 input + 1,913 output tokens per run). No raw signals were in
the returned packet. This small test establishes compatibility, **not a migration
speedup**. The isolated package boundary and transport differ; two runs cannot
attribute the difference to one cause. The privacy-preserving integration bridge
adds a subprocess per whole batch, not per record.


## Visual summary

![Public batching and concurrency measurement](assets/batch-benchmark.png)

![Historical context, cost and latency trade-offs](assets/workflow-tradeoffs.png)

Charts are rendered by `python scripts/render_assets.py` with the `docs` extra.
The public chart reads the checked-in JSON directly. Historical chart values are
explicitly labeled prototype observations. Neither illustration claims a general
accuracy guarantee or a measured whole-agent speedup for this release.


## Native distribution parity

[Source/native observations](../benchmarks/results/2026-09-23-distribution.json) compare
32 synthetic DNS signals across two alternating-order runs, including process startup
and network inference. All four runs returned 32/32 expected judgments with exactly
4,583 input and 1,273 output tokens per run. Returned JSON was 5,660–5,661 characters
in both arms. The native executable averaged 1.838 s versus Python's 1.178 s;
the individual native runs were 2.570 s and 1.105 s. This small sample does not isolate
startup from network variance and does not demonstrate a native speedup.

The native bundle removes installation prerequisites while preserving decisions and
model usage in this fixture. It does not reduce inference cost by itself. The Node
launcher is separately tested through real tarball installation; this timing compares
the underlying native executable, not the extra Node launcher or npm installation.

```sh
python -m benchmarks.distribution --live \
  --native /path/to/native/jev-filter \
  --output local-results/distribution-new.json
```
