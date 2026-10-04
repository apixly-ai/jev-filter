# Independent GEO deployment validation

The deployed technical improvements are observable. **The fixed search sample has not improved yet: exact official URLs remain 0/8 before and after.** Citation, recommendation and installation outcomes were not measured.

Deployment reviewed: [`e138b6965e02eb4768c4d4abc8f4b49b28bae9ca`](https://github.com/apixly-ai/jev-filter/commit/e138b6965e02eb4768c4d4abc8f4b49b28bae9ca), merged in [PR 27](https://github.com/apixly-ai/jev-filter/pull/27). [Documentation deployment run](https://github.com/apixly-ai/jev-filter/actions/runs/37205839607). Search rerun: 2026-10-04 13:32:08 UTC. Independent public HTTP audit: 13:34:17–13:34:25 UTC.

Evidence: [baseline](2026-10-04-baseline.json) and [after](2026-10-04-after.json). Only public metadata is recorded. No paid model trial, indexing resubmission, community contact, or git action was performed by this evaluator.

## Search discovery

| Frozen query group | Before: queries with an exact official URL | After | Result |
| --- | ---: | ---: | --- |
| Brand, two exact strings | 0/2 | 0/2 | Unchanged |
| Task, six exact strings | 0/6 | 0/6 | Unchanged |
| Combined | 0/8 | 0/8 | No observed improvement |

Each exact string was issued once per evaluation using `web.run`, one query per request and `response_length=long`. The second brand query still surfaces a third-party apixly-ai project directory and an unofficial GitHub mirror. Unrelated `jevfilter`/ByteBell name collisions persist. Finding those pages is not finding an official project URL.

This sample does not establish absence from any index. Returned order is not a verified Google or Bing rank; the tool does not expose its provider, region, personalization or index state. The same-day comparison is too early to establish a causal effect. Search result links were not counted as generated-answer citations or recommendations.

## Public technical results

| Check | Baseline | After deployment |
| --- | --- | --- |
| Homepage HTML | 173-byte meta-refresh; no title/H1/description/canonical | 13,465 bytes; substantive content, correct title/H1/description, no refresh |
| Homepage canonical | Absent | `https://apixly-ai.github.io/jev-filter/` |
| Documentation aliases | No canonical | EN aliases consolidate to root; Chinese alias to `index.zh-CN.html` |
| Sitemap | 404 | 200; 51 unique canonical URLs, all 51 return 200 |
| Canonical/alternate consistency | Not present | Canonicals agree with targets; EN/zh-CN alternates reciprocal |
| Three tutorials plus FAQ, both languages | Not included in baseline HTTP measurement | All eight pages return 200 with distinct descriptions, matching `og:url`, meaningful headings and language pairs |
| Required-page local links/assets | Not measured | 615 link references checked; 15 additional targets fetched; no missing target or anchor |
| Public IndexNow key | Not measured | 200; content matches the maintained public verification file |
| Crawler user-agent requests | Not measured | Googlebot, bingbot and OAI-SearchBot user-agent requests return the same 200 homepage; no observed `noindex` header/meta |

The sitemap excludes home aliases, research artifacts and `AGENTS.html`. Root-host `robots.txt` remains 404, which is not evidence of crawl blocking. Crawler user-agent requests demonstrate HTTP accessibility only; they are not observations of genuine crawler visits or indexing.

The homepage JSON-LD identifies the correct source repository, MIT license and package version 0.4.1. It contains no invented rating or adoption claim. Public tutorials retain synthetic-input limits, uncertainty handling, permitted-data boundaries and negative benchmark outcomes.

## One finding for the next iteration

The expanded public audit found incorrect discovery metadata on rendered `README.html` and `README.zh-CN.html`, both included in the sitemap. Their title comes from a `#` comment inside a fenced shell example; their description is the navigation text. The main homepage and all new tutorial/FAQ pages are unaffected.

The title extractor scans raw Markdown for the first `# ` line without excluding fenced blocks; the description extractor accepts the README navigation paragraph. Correct or consolidate the README copies and add a regression fixture that prevents a code comment from becoming a document title. This finding has been reported to the implementing agent. It remains visible in the initial after JSON rather than being silently removed.

## IndexNow receipt

The actual deployment log records HTTP **202**, status `received_key_validation_pending`, **51 submitted URLs**, and **`indexing_verified=false`** at 13:30:43 UTC. The validator did not resend. This confirms receipt with key validation pending; it does not prove crawl, index inclusion or citation.

## Interpretation and next measurement

The release makes the official site substantially clearer and easier to discover technically. A search ranking, discovery or answer-citation gain has **not** been demonstrated. Correct the README metadata finding, verify only affected public pages after redeployment, then preserve the exact frozen query set for later checks after recrawl has had time to occur. Record any new search visibility, citation, recommendation or adoption evidence separately and retain unchanged or unfavorable results.
