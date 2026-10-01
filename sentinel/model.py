"""Round-cadence baseline and an XGBoost model of the next standardised stage."""

from __future__ import annotations

import json
import os
import pickle
import subprocess
from datetime import datetime, timezone

import numpy as np
import xgboost as xgb
from sklearn.metrics import brier_score_loss, precision_score

from sentinel.features import founder_features, industry_as_of, months_between, signal_as_of, venture_rounds
from sentinel.portfolio import STAGE_ORDER, next_stage

HORIZONS = (3, 6, 9)
VERSION = "xgboost-next-stage-v1"
FEATURE_NAMES = [
    "stage",
    "last_amount",
    "months_since_last_vc",
    "own_spacing",
    "employees",
    "traffic",
    "industry_vc_funding",
    "industry_position",
    "prior_startup",
    "university",
]
TRAIN_MONTHS = ((2024, 2), (2024, 4))
EVAL_MONTH = (2024, 5)


def cadence_score(row: dict, horizon: int) -> float | None:
    since = row["months_since_last_vc"]
    spacing = row["own_spacing"]
    if since is None:
        return None
    if not spacing:
        return _clip(since / horizon)
    ratio = since / spacing
    scale = {3: 1.0, 6: 0.85, 9: 0.7}[horizon]
    return _clip(ratio * scale)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def resolve_device() -> str:
    if os.environ.get("ML_DEVICE") != "cuda":
        return "cpu"
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, check=False)
    except FileNotFoundError:
        return "cpu"
    return "cuda" if result.returncode == 0 else "cpu"


def school_code(university: str | None) -> float:
    """Missing school is its own value. A present school is a stable code, not a manual boost."""
    if not university:
        return 0.0
    total = sum(ord(char) for char in university.lower())
    return float(1 + (total % 17))


def _vector(stage, amount, since, spacing, employees, traffic, industry_funding, position, prior, university) -> list[float]:
    stage_index = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else -1
    return [
        float(stage_index),
        _num(amount),
        _num(since),
        _num(spacing),
        _num(employees),
        _num(traffic),
        _num(industry_funding),
        _num(position),
        _num(prior),
        school_code(university),
    ]


def _num(value) -> float:
    if value is None:
        return np.nan
    return float(value)


def _known_clock(rounds: list[dict], year: int, month: int) -> dict | None:
    known = [rnd for rnd in rounds if rnd["year"] and rnd["month"] and (rnd["year"], rnd["month"]) <= (year, month)]
    if not known:
        return None
    last = known[-1]
    gaps = [
        months_between(known[i]["year"], known[i]["month"], known[i + 1]["year"], known[i + 1]["month"])
        for i in range(len(known) - 1)
    ]
    spacing = float(np.median(gaps)) if gaps else None
    return {
        "stage": last["standardized_round"],
        "amount": last["amount"],
        "since": months_between(last["year"], last["month"], year, month),
        "spacing": spacing,
        "known": known,
    }


def _label(rounds: list[dict], stage: str | None, year: int, month: int, horizon: int) -> int:
    upcoming = next_stage(stage)
    if not upcoming:
        return 0
    for rnd in rounds:
        if not rnd["year"] or not rnd["month"] or (rnd["year"], rnd["month"]) <= (year, month):
            continue
        gap = months_between(year, month, rnd["year"], rnd["month"])
        if rnd["standardized_round"] == upcoming and 0 < gap <= horizon:
            return 1
    return 0


def _snapshot_vector(conn, company: dict, rounds: list[dict], year: int, month: int, founders: dict) -> tuple[list[float], dict] | None:
    clock = _known_clock(rounds, year, month)
    if clock is None:
        return None
    signal = signal_as_of(conn, company["id"], year, month)
    industry = industry_as_of(conn, company["industry_name"], year, month)
    employees = None if signal is None else signal["employees"]
    traffic = None if signal is None else signal["traffic"]
    funding = None if industry is None else industry["vc_funding"]
    position = None
    if signal and signal["employees"] and industry and industry["median_employees"]:
        position = signal["employees"] / industry["median_employees"]
    vector = _vector(
        clock["stage"],
        clock["amount"],
        clock["since"],
        clock["spacing"],
        employees,
        traffic,
        funding,
        position,
        founders["prior_startup_count"],
        founders["university"],
    )
    return vector, clock


def train(conn) -> dict:
    device = resolve_device()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM company WHERE found_in_dealroom AND NOT in_portfolio")
        companies = list(cur.fetchall())
    train_x = {horizon: [] for horizon in HORIZONS}
    train_y = {horizon: [] for horizon in HORIZONS}
    eval_rows = {horizon: [] for horizon in HORIZONS}
    for company in companies:
        rounds = venture_rounds(conn, company["id"])
        founders = founder_features(conn, company["id"])
        for year, month in TRAIN_MONTHS:
            built = _snapshot_vector(conn, company, rounds, year, month, founders)
            if built is None:
                continue
            vector, clock = built
            for horizon in HORIZONS:
                train_x[horizon].append(vector)
                train_y[horizon].append(_label(rounds, clock["stage"], year, month, horizon))
        built = _snapshot_vector(conn, company, rounds, EVAL_MONTH[0], EVAL_MONTH[1], founders)
        if built is None:
            continue
        vector, clock = built
        for horizon in HORIZONS:
            eval_rows[horizon].append(
                {
                    "vector": vector,
                    "label": _label(rounds, clock["stage"], EVAL_MONTH[0], EVAL_MONTH[1], horizon),
                    "cadence": cadence_score(
                        {"months_since_last_vc": clock["since"], "own_spacing": clock["spacing"]},
                        horizon,
                    ),
                }
            )
    models = {}
    metrics: dict = {
        "device": device,
        "train_months": [list(item) for item in TRAIN_MONTHS],
        "eval_month": list(EVAL_MONTH),
        "horizons": {},
        "note": "Scores estimate whether the next standardised stage was recorded. They do not mean the company is fundraising.",
    }
    for horizon in HORIZONS:
        label = np.array(train_y[horizon], dtype=int)
        metrics["rows"] = int(len(label))
        if len(label) == 0 or label.sum() == 0 or label.sum() == len(label):
            metrics["horizons"][str(horizon)] = {"trained": False, "reason": "Training label has one class."}
            continue
        matrix = np.array(train_x[horizon], dtype=float)
        model = xgb.XGBClassifier(
            n_estimators=16,
            max_depth=2,
            learning_rate=0.3,
            objective="binary:logistic",
            eval_metric="logloss",
            tree_method="hist",
            device=device,
        )
        model.fit(matrix, label)
        fitted = model.predict(matrix)
        report = {
            "trained": True,
            "train_precision": float(precision_score(label, fitted, zero_division=0)),
            "positive_labels": int(label.sum()),
        }
        held = eval_rows[horizon]
        if held:
            eval_matrix = np.array([row["vector"] for row in held], dtype=float)
            eval_label = np.array([row["label"] for row in held], dtype=int)
            probabilities = model.predict_proba(eval_matrix)[:, 1]
            report["precision_at_top"] = _precision_at_top(eval_label, probabilities)
            cadence_scores = np.array([0.0 if row["cadence"] is None else row["cadence"] for row in held], dtype=float)
            report["cadence_precision_at_top"] = _precision_at_top(eval_label, cadence_scores)
            if len(np.unique(eval_label)) > 1:
                report["brier"] = float(brier_score_loss(eval_label, probabilities))
            report["beats_cadence"] = report["precision_at_top"] >= report["cadence_precision_at_top"]
        metrics["horizons"][str(horizon)] = report
        models[horizon] = model.get_booster()
    six = metrics["horizons"].get("6", {})
    metrics["beats_cadence"] = bool(six.get("beats_cadence"))
    metrics["cadence_precision_at_6"] = six.get("cadence_precision_at_top")
    _save(conn, metrics, models, device)
    return metrics


def _precision_at_top(labels: np.ndarray, scores: np.ndarray, fraction: float = 0.25) -> float:
    if len(labels) == 0:
        return 0.0
    order = np.argsort(-scores, kind="mergesort")
    k = max(1, int(round(len(labels) * fraction)))
    return float(labels[order[:k]].mean())


def score_portfolio(conn) -> None:
    from sentinel.features import feature_row

    models = _load(conn)
    gains = _gains(models.get(6))
    with conn.cursor() as cur:
        cur.execute("DELETE FROM prediction")
        cur.execute("SELECT * FROM company WHERE in_portfolio")
        companies = list(cur.fetchall())
    for company in companies:
        if not company["found_in_dealroom"]:
            continue
        row = feature_row(conn, company)
        year, month = row_year_month(conn, company["id"])
        industry = industry_as_of(conn, company["industry_name"], year, month)
        funding = None if industry is None else industry["vc_funding"]
        vector = np.array(
            [
                _vector(
                    row["stage"],
                    row["last_amount"],
                    row["months_since_last_vc"],
                    row["own_spacing"],
                    row["employees"],
                    row["traffic"],
                    funding,
                    row["industry_position"],
                    row["prior_startup_count"],
                    row["university"],
                )
            ],
            dtype=float,
        )
        missing = list(row["missing"])
        if company.get("jobs_open") is not None:
            missing.append("hiring_is_current_only")
        for horizon in HORIZONS:
            model_score = None
            booster = models.get(horizon)
            if booster is not None:
                model_score = float(booster.predict(xgb.DMatrix(vector))[0])
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO prediction (
                        company_id, horizon_months, next_stage, cadence_score, model_score,
                        months_since_last_vc, own_spacing, model_version, feature_gains,
                        missing_features, as_of
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, DATE '2026-10-01')
                    """,
                    (
                        company["id"],
                        horizon,
                        row["next_stage"],
                        cadence_score(row, horizon),
                        model_score,
                        row["months_since_last_vc"],
                        row["own_spacing"],
                        VERSION,
                        json.dumps(gains),
                        json.dumps(missing),
                    ),
                )
    conn.commit()


def row_year_month(conn, company_id: str) -> tuple[int, int]:
    signal = signal_as_of(conn, company_id, 9999, 12)
    if signal is None:
        return 2026, 10
    return signal["year"], signal["month"]


def _save(conn, metrics: dict, models: dict, device: str) -> None:
    blob = pickle.dumps({horizon: booster.save_raw() for horizon, booster in models.items()})
    with conn.cursor() as cur:
        cur.execute("DELETE FROM model_run WHERE version = %s", (VERSION,))
        cur.execute(
            """
            INSERT INTO model_run (version, trained_at, device, metrics, payload)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            """,
            (VERSION, datetime.now(timezone.utc), device, json.dumps(metrics), blob),
        )
    conn.commit()


def _load(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT payload FROM model_run WHERE version = %s", (VERSION,))
        row = cur.fetchone()
    if row is None or row["payload"] is None:
        return {}
    raw = pickle.loads(bytes(row["payload"]))
    loaded = {}
    for horizon, saved in raw.items():
        booster = xgb.Booster()
        booster.load_model(bytearray(saved))
        loaded[int(horizon)] = booster
    return loaded


def _gains(booster) -> dict:
    if booster is None:
        return {}
    try:
        scores = booster.get_score(importance_type="gain")
    except xgb.core.XGBoostError:
        return {}
    ranked = []
    for key, value in scores.items():
        name = key
        if key.startswith("f") and key[1:].isdigit() and int(key[1:]) < len(FEATURE_NAMES):
            name = FEATURE_NAMES[int(key[1:])]
        ranked.append((name, float(value)))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return dict(ranked[:5])
