# XYZ Capital | Portfolio Sentinel

AI built a portfolio intelligence dashboard using the Dealroom API to surface high-potential companies within an investor’s existing portfolio, helping VC teams identify opportunities to commit an early ticket at a potential discount and participate in the next raise. The dashboard shows priority signals, peer comparisons and model-training results, with XGBoost (highly efficient machine learning algorithm that builds a chain of decision trees to solve complex problems) estimating fundraising likelihood over 3, 6 and 9 months using API data on funding-round dates, amounts and stages, headcount, monthly web traffic, UK industry venture funding, and founders’ previous startups and universities, alongside derived features for round spacing, time since the last raise and relative industry position.

## Architecture

Dealroom is read during import. PostgreSQL is the system of record after that. The dashboard, REST paths, and MCP read stored rows and do not call Dealroom when someone asks a question.

`sentinel/dealroom.py` is the only module that knows Dealroom URLs. `python -m sentinel.sync` runs `sentinel.live_sync`, which checks each holding against its pinned domain and UUID, then writes company, round, filing, traffic, team, and headcount rows. `python -m sentinel.pipeline` fits `xgboost-dealroom-live-v2` in `sentinel/real_model.py` on funding history from a separate UK cohort, and writes predictions and alerts. `uvicorn sentinel.api:app` serves the page, REST, and `POST /mcp` from that database. A model connected through MCP receives those tool results. It does not hold the Dealroom client secret and does not query the vendor API.

Docker Compose starts Postgres 16 and the same API process. The web process creates tables only. Sync and the pipeline stay separate commands, so starting the server does not train a model or load demo rows.

## Dealroom API

Live import uses the Dealroom beta API at `https://api.beta.dealroom.app`. The adapter exchanges `DEALROOM_CLIENT_ID` and `DEALROOM_CLIENT_SECRET` at `https://accounts.dealroom.co/oauth/token` with the client-credentials grant, audience `https://api.beta.dealroom.app`. Every data request sends `Authorization: Bearer` and `X-Client-Id`. The OpenAPI reference is `https://developers.beta.dealroom.co/openapi.yaml`.

| Use | Endpoint | What is kept |
|---|---|---|
| Holding identity | `GET /data/search` | One company match by pinned domain, or by exact name when no domain is set |
| Holding record | `GET /data/companies/{uuid}` | Identity, website, headquarters, taxonomy |
| Rounds | `GET /data/companies/{uuid}/funding-rounds` | Dated amounts, venture flag, standardised stage. Pages follow `page.next_cursor` |
| Filings | `GET /data/companies/{uuid}/financials` | Revenue and employee filings. Optional |
| Traffic | `GET /data/companies/{uuid}/web-traffic` | Monthly visits. Optional |
| Team | `GET /data/companies/{uuid}/team` | Founder experience and university. Optional |
| Headcount | `GET /data/companies/{uuid}/headcount-breakdown` | Employee counts. Percentage rows are not headcount. Optional |
| Training cohort | `GET /data/companies` | Up to 40 UK-headquartered VC-backed companies per founding year, 2015–2022, Mature and Outside Tech excluded. Funding histories only |

The six holdings are loaded with the full company record. The training cohort is loaded with funding rounds only, so current founder profiles and traction never enter a historical training row. `GET /analytics/timeseries?metric=vc_funding` and the wider UK company-panel query remain in the adapter. They do not feed `xgboost-dealroom-live-v2`.

## Set up and run with real data

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Set your Dealroom credentials and `DATABASE_URL` in the local `.env`. Export `DATABASE_URL` into your shell if you use a database other than the default. Keep this file private.

Start PostgreSQL, then import and train:

```bash
python -m sentinel.sync
python -m sentinel.pipeline
uvicorn sentinel.api:app --host 127.0.0.1 --port 8001
```

Use `.venv/bin/python` and `.venv/bin/uvicorn` when running from the project virtual environment. PostgreSQL must be available at `DATABASE_URL`; its default is the local Sentinel database. The Dealroom adapter reads the existing gitignored `.env` containing `DEALROOM_CLIENT_ID` and `DEALROOM_CLIENT_SECRET`. It never prints the credentials.

The web server creates schema only. It does **not** automatically load demo data or train a model. `docker compose up --build` starts the database and API at port 8000; explicitly run the sync and pipeline against that database to populate it.

## What the live import does

`sentinel.sync` calls `sentinel.live_sync`. It verifies each holding against its website domain and pinned API UUID, then fetches company details, all funding-round pages, financials, web traffic, team and headcount breakdown. Optional endpoint failures produce missing data; they never produce invented observations. Headcount percentages are not employee counts. Standardised stages are never backfilled from self-reported round names. Year-only rounds are excluded from monthly modelling.

For training, it takes up to 40 UK-headquartered VC-backed companies from each founding-year cohort, 2015–2022, excluding Mature and Outside Tech. The country ID (93) was verified from the API's UK headquarters metadata; the documented `hq_location` filter is used. This is a bounded sample in the API's default order, **not** a random or exhaustive population sample. Closed companies are not explicitly excluded, but current VC-backed/non-mature selection still creates survivorship bias.

Training imports only those companies' funding histories. It does not import current founder profiles or traction into historical training rows. The live provenance marker is `company.source = 'dealroom_live'`; the model selects only that marker. Holdings are excluded from training.

Requests share a rate limiter below five requests/second, retry transient errors, refresh a rejected token once, and follow `page.next_cursor` through the `cursor` request parameter. Successful responses are cached for 24 hours in the gitignored `.dealroom-cache/`. `live-manifest.json` records the cohort filters, sample counts, API tier and fetch time. Clear expired cache entries when a fresh same-day request is required. Responses with `locked` company records are rejected. The API reports a free tier; absent amounts remain missing, and access coverage is a limitation.

Before applying a completed import, the importer saves a recoverable JSON snapshot of the affected tables in `.dealroom-cache/before-live-*.json`. It replaces the holdings' demo facts, removes the identifiable synthetic `panel-*` rows and demo industry series, clears stale predictions/alerts, and removes the fixture's exact seeded Nila employee target. Other fund targets are retained. The pipeline must then be run to rebuild predictions and alerts.

## Data fetched from Dealroom

Endpoints, authentication, and the fields kept from each response are in **Dealroom API** above. The live training cohort fetches funding histories only. The six features below are the inputs to the current live XGBoost model. Industry-funding adapters and the legacy fixture model remain in the code, but industry time series, founder profiles and traction metrics do not feed the live model.

## Model and validation

The live model is `xgboost-dealroom-live-v2`, implemented in `sentinel/real_model.py`. It predicts whether Dealroom records the **next standardised stage** in 3, 6 or 9 months. This is not a prediction of any cash raise, an active fundraising process, or investment quality.

Six historical funding features are built identically for training and scoring:

- Last standardised venture stage.
- Log of the last venture amount in USD.
- Months since the last venture round.
- Median gap between previous venture rounds.
- Number of venture rounds known by the snapshot.
- Log of total known venture funding (missing if any amount is unknown).

Debt and grants do not start the venture clock. Unknown stages and undated rounds cannot establish a modelling snapshot. Missing inputs stay missing. Current founder experience, university, current headcount and current traffic are excluded because their historical availability cannot be established from these imports.

A stable company-level split assigns 60% to training, 20% to calibration and 20% to testing. Training uses quarterly snapshots from January 2018 through March 2022. Calibration uses 2023 snapshots; testing uses 2025 snapshots. Even nine-month outcome windows finish before the next split begins, and all test outcomes finish by July 2026. No company appears in multiple splits. Snapshots within one company remain correlated.

XGBoost uses fixed parameters and a fixed seed. A logistic calibrator is fit on the separate calibration companies. Stored metrics include sample/company/positive counts, Brier score, prevalence-baseline Brier score, average precision, ROC AUC and score range. A horizon needs at least 50 snapshots and 10 positive and negative outcomes in every split. Portfolio estimates are withheld unless the held-out Brier score and average precision beat the prevalence baseline, calibration is monotonic, and the company's stage has at least 10 training companies. Non-UK holdings are withheld because the training sample is UK-only.

Passing these checks is a minimum gate, not proof of production reliability. The UI labels estimates experimental. The bounded cohort, selection bias, missing funding events and correlated snapshots constrain what the scores mean. A 70% threshold identifies high signals; if no company clears it, the dashboard says so rather than manufacturing an alert.

## Dashboard and API

The dashboard at `/` supports company search, stage filters, signal sorting and company detail panels. A 3-month/6-month switch updates the portfolio outlook, signals and company estimates, with 3 months selected by default. Suggested review actions are labelled as actions, rather than predicted events. The training report exposes validation counts, model status and feature gains. `/portfolio?horizon=3` or `/portfolio?horizon=6` returns the selected portfolio rows and model validation report.

A toggleable, fictional Asterion Quantum example illustrates an 84/100 high signal and the follow-up workflow. Its score is preset and excluded from portfolio counts, alerts and model training. Real scores remain unavailable when validation fails. The UI shows missing scores as unavailable, with their reasons in company detail.

Existing endpoints remain available: `/alerts`, `/companies/{name}/changes`, `/companies/{name}/prediction`, `/companies/{name}/industry`, `/companies/{name}/targets`, `/companies/{name}/brief`, `/retrieve?q=`, and JSON-RPC `/mcp`. REST and MCP call the same stored-data functions. Fund-target and financing-pressure alerts require entered evidence; the model score does not determine their severity.

Live industry series and competitor medians are not populated by the funding-only training import. Their absence is displayed as missing, not zero. Old synthetic industry comparisons are removed.

## Tests and explicit demo mode

```bash
SKIP_DB=1 pytest -q
```

This runs normalization, identity, pagination and model temporal-boundary checks without altering the portfolio database. The database integration tests reload synthetic fixtures: run them **only against a disposable test database**.

`python -m sentinel.pipeline --fixture` explicitly resets the database to synthetic demo records and trains the legacy example model. Never use this command against a real imported portfolio. The fixture model and its old 91%/3% outputs are not real-world fundraising probabilities.

API reference: https://developers.beta.dealroom.co/openapi.yaml. Analyst definitions and scope conventions: `apis/dealroom-api-analysis.md`. `dealroom.sh` is an independent top-valuations example and does not populate the dashboard.

## Credentials and private data

Credentials are configured locally, never in source. `.gitignore` excludes `.env`, token files, API response caches, PostgreSQL data directories, model files, local exports, backups and dashboard captures. `.dockerignore` excludes these local artifacts from the build context. The checked-in portfolio names and domains describe a public example portfolio; fixture numbers and the Asterion scenario are illustrative. Live API records, database contents and training artifacts are not distributed with this repository. The Compose database credentials are local development defaults.

### Global peer benchmarks
Run `.venv/bin/python -m sentinel.peer_sync` to refresh `sentinel/static/peers.json`. The dashboard reads this snapshot for live company comparisons. Up to 40 candidates per holding are matched globally on Dealroom industry tags and current growth stage (not exact funding round). Holdings and locked records are excluded. Medians require five independent peers with a value in the same period. Annual employee observations retain year precision; traffic retains monthly precision. No forward filling is performed. Missing classifications remain unmatched. This import is separate from the UK fundraising training cohort and does not retrain that model.
