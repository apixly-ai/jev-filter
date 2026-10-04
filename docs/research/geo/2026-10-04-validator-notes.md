# Independent GEO validation notes

Evaluation date: 2026-10-04. Search baseline captured at 13:15:08 UTC; public HTTP checks captured at 13:18:40 UTC. This evaluator did not implement the site changes. [Machine-readable baseline](2026-10-04-baseline.json) contains frozen queries and public result metadata.

## Before changes

Eight queries were issued separately using the same `web.run` search surface and `response_length=long`: two brand queries and six task queries. None of the returned samples contained an exact official apixly-ai repository, Pages, npm, or Python distribution URL. This does **not** establish absence from any search index. The tool does not expose engine, location, personalization, or verified SERP rank; the stored order is returned order only.

The second brand query did surface an apixly-ai project entry in a third-party directory and an unofficial GitHub mirror. Brand-name collisions include a different `jevfilter` Python distribution and a ByteBell directory entry. Count official URLs separately from third-party mentions and unrelated names.

| Public URL | Status | Observed baseline |
| --- | --- | --- |
| [Pages root](https://apixly-ai.github.io/jev-filter/) | 200 | 173-byte meta-refresh; no title, H1, description, or canonical |
| [Documentation](https://apixly-ai.github.io/jev-filter/docs/) | 200 | Generic description; no canonical |
| [Benchmarks](https://apixly-ai.github.io/jev-filter/docs/benchmarks.html) | 200 | Same generic description; no canonical |
| [Sitemap](https://apixly-ai.github.io/jev-filter/sitemap.xml) | 404 | No sitemap at this URL |
| [Project robots file](https://apixly-ai.github.io/jev-filter/robots.txt) | 404 | Not the host-root robots policy |
| [Host-root robots file](https://apixly-ai.github.io/robots.txt) | 404 | No robots file observed; this is not evidence of crawl blocking |

No generated-answer citation or recommendation test was performed. Search discovery, answer citation, recommendation, and actual installation are different outcomes.

## Evidence and practical priorities

[Google's current AI optimization guide](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide) prioritizes original, useful content and normal search fundamentals. Google does not use `llms.txt` or special AI markup to improve visibility. It does not require tiny content chunks or a special writing style. Pages must be indexed and eligible for snippets; fulfilling requirements does not guarantee crawling, indexing, or display. Avoid mass-producing query variants or manufacturing mentions. For this project, runnable examples and honestly scoped benchmark evidence are a better application than generic promotional pages.

[Google canonical guidance](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls) supports consistent absolute canonical URLs and internal links. [Sitemap guidance](https://developers.google.com/search/docs/crawling-indexing/sitemaps/overview) treats sitemaps as URL-discovery assistance, not guaranteed indexing. Verify the generated sitemap references live canonical pages and does not contain redirects or deployment-only files.

[Bing AI Performance](https://blogs.bing.com/webmaster/2026/2/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview/) reports citations, cited pages, and sampled grounding phrases across supported AI surfaces. These are not rank or recommendation metrics. Verified webmaster data would complement the fixed public query sample. [IndexNow documentation](https://www.indexnow.org/documentation) allows a key hosted outside the root with an explicit `keyLocation`. Notify only deployed URLs under the verified scope. A notification acceptance is not proof of indexing or citation.

[Official OpenAI crawler documentation](https://developers.openai.com/api/docs/bots) distinguishes `OAI-SearchBot` search crawling from `GPTBot` training. The settings are independent. `ChatGPT-User` is user-initiated fetching, not automatic search indexing. The documented approximately 24-hour delay concerns changes to robots policy; it does not promise an indexing or ranking deadline. On a GitHub Pages project site, a `/jev-filter/robots.txt` file does not control the host-root policy.

The [GEO paper](https://arxiv.org/html/2311.09735v3) measures source visibility using attributed word count/position and a model-scored impression metric. Its main setup supplies Google's top five sources to GPT-3.5-turbo and averages five samples. The 10K-query benchmark tests changes to an already selected source. The Perplexity experiment uploads source text for 200 queries and restricts answers to those files. Thus, its reported gains test answer attribution under controlled source availability, not live discovery of a new project. Effects vary by domain and source position, including negative results. The reported improvements are not a forecast for Jev Filter.

## Exact rerun contract

After deployment, rerun the exact eight strings from the JSON file with the same tool/options. Retain failures and unchanged results. Do not substitute `site:` queries, a different provider, or brand-heavy wording into the nonbrand comparison. Record these optional diagnostics separately.

Public fetch checks should verify substantive HTML at the root, distinct descriptions, absolute canonicals, reachable tutorial links, sitemap status and URL validity, and accurate limits beside benchmark numbers. Confirm deployment by fetching its actual public contents, not only by seeing an Actions success.

A same-day search rerun may remain unchanged while public technical checks improve. Report that distinction directly. Establish search improvement only when fixed-query visibility changes are observed, then investigate recrawl timing and variation before attributing causality. If answer trials are later authorized, save prompts, engine/model, date, citations, and recommendations separately; do not treat search result links as generated-answer citations.
