# Portfolio Sentinel

A VC asks “should I preempt this raise?” or “how is this company doing?”. A sync reads Dealroom and writes PostgreSQL. The page, the REST paths, and MCP all read those stored rows. OpenAI does not call Dealroom. A score is a model output with a `model_version`. It is not a statement that the company is fundraising, and it is not a decision to lead the round.

The example book is Phoenix Court: six public companies and three stealth pre-seeds. Competitors are other companies in the same UK industry and stage band. Industries are not added together. 2026 industry months are marked partial. Headquarters are United Kingdom only, and each company uses its industry tag rather than a same-named sector tag.

| Company | Stage tag in this book | Industry |
|---|---|---|
| Nila | Pre-Seed | Health |
| Frontier Computing | Pre-Seed | AI and machine learning |
| Grafit | Seed | Manufacturing and industry |
| Bron | Seed | Finance and payments |
| Catalog | Series A | Marketplaces |
| Dexory | Series A | Business operations |
| Stealth Climate | Pre-Seed | Climate |
| Stealth Deep Tech | Pre-Seed | Deep tech |
| Stealth Transport | Pre-Seed | Transportation |

Catalog and Dexory are tagged Series A here. The stored round stage is whatever Dealroom returns on a live sync. The three stealth names are expected misses and are stored as not found.

## Run

```bash
docker compose up --build
```

Postgres and the API come up. With an empty database the API loads a recorded Dealroom fixture, trains on CPU, and serves http://localhost:8000. The page shows the six-month readiness signal and an SVG of the company against the competitor median.

`ML_DEVICE=cpu` is the default. XGBoost uses CUDA only when `ML_DEVICE=cuda` and `nvidia-smi` succeeds. This machine has no CUDA device, so the first model runs on CPU. The same training code is what later runs on an NVIDIA GPU.

Live sync, from the host, with `DEALROOM_CLIENT_ID` and `DEALROOM_CLIENT_SECRET` in the gitignored `.env`:

```bash
python -m sentinel.sync
python -m sentinel.pipeline
```

`python -m sentinel.pipeline --fixture` reloads the recorded rows and retrains without calling Dealroom. Credentials are never committed.

## Dealroom data a live sync fetches

`python -m sentinel.sync` is the only path that calls Dealroom. Docker Compose and `python -m sentinel.pipeline --fixture` load the recorded fixture and do not call the API. The three stealth names are not requested. A search miss is stored as not found.

**Each of the six public holdings.** Search by exact company name (`GET /data/search`, limit 5, type `company`), then load that uuid:

| Endpoint | What is kept |
|---|---|
| `GET /data/companies/{uuid}` | Headquarters country, open jobs, valuation year and month |
| `GET /data/companies/{uuid}/funding-rounds` | Up to 100 rounds: year, month, amount, standardised stage, and whether the round is venture |
| `GET /data/companies/{uuid}/financials` | Filing year, revenue, and employees. An employee count is also stored as that year's December signal |
| `GET /data/companies/{uuid}/web-traffic` | Monthly visits |
| `GET /data/companies/{uuid}/team` | Up to 20 people: name, number of companies founded, and the first listed university |
| `GET /data/companies/{uuid}/headcount-breakdown` | Monthly employee counts. Rows that are a share or a percentage are dropped |

Financials, traffic, team, and headcount are optional. A failed call is stored as empty.

**One venture-funding series per industry on the book.** `GET /analytics/timeseries?metric=vc_funding`. The filter is United Kingdom headquarters, venture rounds only, Mature excluded (`growth_stage` 412), Outside Tech excluded (`taxonomy_id` 1102801), and that industry's taxonomy id. The industry family (id ending in 03) is used rather than a same-named sector tag. Months in 2026 are marked partial. Each industry is fetched on its own and the series are not added together.

**A UK panel for training and competitor medians.** `GET /data/companies` with limit 24, venture-backed, Mature excluded, Outside Tech excluded. A row is kept only when its headquarters is the United Kingdom and its name is not already one of the six holdings. Each kept company is loaded with the same company endpoints and stored outside the portfolio. Employee and traffic medians are then computed in Postgres from that panel. Those medians are not a Dealroom dataset.

`./dealroom.sh` is a separate request. It lists the 10 highest-valued VC-backed companies founded since 2020 and does not fill these tables.

## What the model uses

Feature names live in `FEATURE_NAMES` in [sentinel/model.py](sentinel/model.py).

Dealroom history that a past month can rebuild: standardised stage, last venture amount, months since the last venture round, the company’s own spacing, employees, traffic, and the industry venture-funding level. Debt does not reset the clock. Hiring is a current flag only, because the jobs endpoint returns active posts. Runway, cash, and burn exist only when the fund has saved them.

Founders: `prior_startup` and `university`. Missing university is its own value. The weight is the gain the training history assigns. A school is not given a manual boost.

Industry position: each company series divided by that company’s own UK industry series, then the geometric mean of the ratios that exist. A missing series is dropped and listed. It is a feature, not the number the brief leads with.

The comparison model is the round-cadence rule. XGBoost is fit on a UK panel wider than the nine holdings, scored on a later month, and kept beside the cadence rule. Libraries are `xgboost`, `scikit-learn` (the time split, precision at the top of the list, and a Brier calibration check), and `numpy`.

## REST

| Path | Returns |
|---|---|
| `GET /` | Local page for one company |
| `GET /alerts` | Open alerts for the book |
| `GET /companies/{name}/changes?lookback=6` | Feature change over the lookback |
| `GET /companies/{name}/prediction` | Cadence rule and XGBoost scores at 3, 6, and 9 months |
| `GET /companies/{name}/industry` | Company-versus-industry ratios and the geometric mean |
| `GET /companies/{name}/targets` | Fund targets and Dealroom actuals, or the reason none were entered |
| `GET /companies/{name}/brief` | Readiness signal, competitor graph, evidence |
| `GET /retrieve?q=` | Stored passages for RAG |
| `POST /mcp` | MCP JSON-RPC (`initialize`, `tools/list`, `tools/call`) |

MCP is at `http://localhost:8000/mcp`. [.cursor/mcp.json](.cursor/mcp.json) points at it. REST and MCP call the same functions.

Tools: `retrieve_context`, `get_portfolio_alerts`, `get_company_changes`, `get_company_prediction`, `get_industry_position`, `get_company_targets`, `generate_company_brief`.

`retrieve_context` searches stored passages and returns source, date, and `fetched_at`. A question with no stored passage is answered as missing.

`generate_company_brief` answers in this order: the readiness signal for the next stage, the competitor graph, then the evidence. The graph is an SVG with months on the horizontal axis and two lines, the company and the competitor median. The reply says the signal is not a decision to lead.

Alerts are `FUNDRAISING_WINDOW`, `EARLY_SIGNAL`, `TARGET_MISS`, `FINANCING_PRESSURE`, `PEER_MARKET_SHIFT`, and `DATA_ANOMALY`. Severity is `info`, `watch`, `attention`, or `urgent`. A model score alone cannot set severity. `TARGET_MISS` and `FINANCING_PRESSURE` appear only when the fund has entered a target or a short runway figure.

## Questions a VC can ask

- Should I preempt a Series A for Nila?
- How is Frontier Computing doing at this stage, against its competitors?
- Is Grafit ready for its next raise?
- Is Bron hitting its targets, and what do its founders’ prior companies and universities do to the score?
- Which portfolio companies look ready to preempt this month?
- What do we have stored for Stealth Climate?

## Tests

```bash
pytest
```

The tests use the recorded fixture. They do not need a Dealroom key. PostgreSQL has to be listening at `DATABASE_URL` (the default matches `docker compose`).

## Dealroom client

`./dealroom.sh` still loads `.env` and lists the 10 highest-valued VC-backed companies founded since 2020. Counts and charts follow [apis/dealroom-api-analysis.md](apis/dealroom-api-analysis.md): venture rounds only, Mature and Outside Tech excluded, headquarters attribution, industry tag rather than a same-named sector tag, and the current year labeled partial.
