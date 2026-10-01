"""PostgreSQL company database. Dealroom rows are stored as internal company facts."""

from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS company (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    in_portfolio BOOLEAN NOT NULL DEFAULT FALSE,
    hq_country TEXT,
    industry_name TEXT,
    stage TEXT,
    jobs_open INTEGER,
    valuation_year INTEGER,
    valuation_month INTEGER,
    found_in_dealroom BOOLEAN NOT NULL DEFAULT FALSE,
    source TEXT,
    fetched_at TIMESTAMPTZ,
    source_endpoint TEXT
);
CREATE TABLE IF NOT EXISTS funding_event (
    id BIGSERIAL PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    year INTEGER,
    month INTEGER,
    amount DOUBLE PRECISION,
    standardized_round TEXT,
    is_vc_round BOOLEAN NOT NULL DEFAULT FALSE,
    source TEXT,
    fetched_at TIMESTAMPTZ,
    source_endpoint TEXT
);
CREATE TABLE IF NOT EXISTS monthly_signal (
    company_id TEXT NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    employees DOUBLE PRECISION,
    traffic DOUBLE PRECISION,
    source TEXT,
    fetched_at TIMESTAMPTZ,
    source_endpoint TEXT,
    PRIMARY KEY (company_id, year, month)
);
CREATE TABLE IF NOT EXISTS filing (
    company_id TEXT NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    revenue DOUBLE PRECISION,
    employees DOUBLE PRECISION,
    source TEXT,
    fetched_at TIMESTAMPTZ,
    source_endpoint TEXT,
    PRIMARY KEY (company_id, year)
);
CREATE TABLE IF NOT EXISTS industry_month (
    industry_name TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    vc_funding DOUBLE PRECISION,
    median_employees DOUBLE PRECISION,
    median_traffic DOUBLE PRECISION,
    partial BOOLEAN NOT NULL DEFAULT FALSE,
    source TEXT,
    fetched_at TIMESTAMPTZ,
    source_endpoint TEXT,
    PRIMARY KEY (industry_name, year, month)
);
CREATE TABLE IF NOT EXISTS founder (
    id BIGSERIAL PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    name TEXT,
    prior_startup_count INTEGER,
    university TEXT,
    source TEXT,
    fetched_at TIMESTAMPTZ,
    source_endpoint TEXT
);
CREATE TABLE IF NOT EXISTS fund_target (
    id BIGSERIAL PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    metric TEXT NOT NULL,
    target_value DOUBLE PRECISION NOT NULL,
    period TEXT
);
CREATE TABLE IF NOT EXISTS model_run (
    version TEXT PRIMARY KEY,
    trained_at TIMESTAMPTZ NOT NULL,
    device TEXT NOT NULL,
    metrics JSONB NOT NULL,
    payload BYTEA
);
CREATE TABLE IF NOT EXISTS prediction (
    company_id TEXT NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    horizon_months INTEGER NOT NULL,
    next_stage TEXT,
    cadence_score DOUBLE PRECISION,
    model_score DOUBLE PRECISION,
    months_since_last_vc INTEGER,
    own_spacing DOUBLE PRECISION,
    model_version TEXT,
    feature_gains JSONB,
    missing_features JSONB,
    as_of DATE NOT NULL,
    PRIMARY KEY (company_id, horizon_months)
);
CREATE TABLE IF NOT EXISTS alert (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence JSONB NOT NULL,
    missing JSONB NOT NULL,
    next_step TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS passage (
    id BIGSERIAL PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    source TEXT,
    as_of DATE,
    fetched_at TIMESTAMPTZ
);
"""


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://sentinel:sentinel@localhost:5432/sentinel",
    )


@contextmanager
def connect():
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        yield conn


def init_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()


def reset_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            DROP TABLE IF EXISTS passage, alert, prediction, model_run, fund_target,
                founder, industry_month, filing, monthly_signal, funding_event, company
            CASCADE
            """
        )
    conn.commit()
    init_schema(conn)
