# README and documentation design

[简体中文](readme-design.zh-CN.md)

The homepage leads with the outcome: **give the agent the signal, keep the evidence**.
It then shows three concrete advantages—focused context, traceable decisions and
program-verified execution—before installation, dated measurements and integration.
The command catalogue is collapsible so it supports the narrative rather than owning it.

## Visual system

- Repository-owned, bilingual SVG hero: dark navy, mint signal, violet judgment and a small evidence packet illustrating the runnable DNS example.
- GitHub-compatible HTML, relative assets and standard Markdown. The README works without scripts or a hosted renderer.
- Responsive documentation landing: the same visual language, clear primary action, task-oriented routes, horizontal navigation on narrow screens and keyboard-visible focus states.
- Actual data stays in text and tables, with source links. Historical charts remain available inside a details panel; no decorative chart invents a performance result.

The hero combines a runnable example with a prominent proof strip: the fresh
91.6–97.2% returned-context reduction is directly labelled “24 real agent runs ·
2026-10-04”. It also shows traceable evidence and the four core integration routes.
English and Chinese claims, dates, scope and limitations must be kept synchronized.
The README does not promise universal
speed, cost savings, automatic correctness or open-web completion rates.

## Evidence and honesty

The strongest measured hook is the 2026-10-04 whole-operation benchmark's 91.6–97.2%
reduction in returned tool context. The same table exposes the cost range, latency
regressions and synthetic scope. Hosted fixture passes sit beside the weaker real-web
audit. New release experiments must keep baseline, treatment, failures, review rates,
returned context, full timing and actual per-model usage visible; offline replay and
live inference must be named separately.

Optional hybrid retrieval widens candidates. Its recall/precision/context trade-off
must not be described as an unconditional improvement. Offline evaluation diagnoses
probabilities and selects thresholds from supplied calibration groups; it does not
fit a calibrated production probability model.

## Maintain and verify

Edit `docs/assets/hero.svg` and `hero.zh-CN.svg` directly. Styling for the documentation
site is in `docs/assets/docs.css`; `scripts/build_docs.py` copies it into the build.
Fresh charts and social images are reproducible with `python scripts/render_live_assets.py`
after installing `.[docs,browser-test]`. `scripts/render_assets.py` rebuilds only historical
charts and preserves the maintained hero.

```sh
python scripts/build_docs.py
python scripts/check_docs.py
```

Before publication, render desktop and mobile pages, inspect bilingual hero legibility,
check tables and code for page overflow, follow installation and integration examples,
and compare all metric claims with their source files. Keep local screenshots outside
published source (`local-results/`).

Earlier design references retained for context: [uv](https://github.com/astral-sh/uv/blob/main/README.md),
[bat](https://github.com/sharkdp/bat/blob/master/README.md),
[GitHub README guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)
and [GitHub image/link syntax](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax).
No third-party artwork is incorporated.
