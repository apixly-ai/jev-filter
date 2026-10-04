| Main model | Scenario | Raw / filtered exact | Tool bytes less | Main input tokens less | Mean latency change | Cold API equivalent less | Cache-adjusted equivalent less |
|---|---|---:|---:|---:|---:|---:|---:|
| gpt-5.6-luna | code-search | 2/2 / 2/2 | +96.1% | +23.1% | +8.4% | +14.2% | +20.8% |
| gpt-5.6-luna | triage | 2/2 / 2/2 | +97.2% | +22.5% | +12.3% | +3.1% | +4.6% |
| gpt-5.6-luna | exec | 2/2 / 2/2 | +91.6% | +5.9% | +0.1% | -1.1% | -12.0% |
| gpt-6-astra | code-search | 2/2 / 2/2 | +96.1% | +22.5% | +5.0% | +22.0% | +33.1% |
| gpt-6-astra | triage | 1/2 / 2/2 | +97.2% | +23.8% | -15.3% | +23.2% | +34.6% |
| gpt-6-astra | exec | 2/2 / 2/2 | +91.6% | +5.1% | +18.4% | +4.8% | +70.6% |

Optional caller-supplied API-equivalent estimates are not a subscription invoice. Provider prompt caching is measured separately from inference-result caching. Missing usage or absent rates yield null cost, never zero.
