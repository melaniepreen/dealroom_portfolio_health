"""Train, score, and raise alerts from the company database."""

import json

from sentinel.alerts import rebuild_alerts
from sentinel.db import connect, init_schema
from sentinel.model import score_portfolio, train


def prepare(conn) -> dict:
    metrics = train(conn)
    score_portfolio(conn)
    rebuild_alerts(conn)
    return metrics


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Train scores from the company database.")
    parser.add_argument("--fixture", action="store_true", help="Load the recorded Dealroom fixture first.")
    args = parser.parse_args()
    with connect() as conn:
        init_schema(conn)
        if args.fixture:
            from sentinel.fixture import load_fixture

            load_fixture(conn)
        metrics = prepare(conn)
    print(json.dumps({"device": metrics.get("device"), "beats_cadence": metrics.get("beats_cadence")}, default=str))


if __name__ == "__main__":
    main()
