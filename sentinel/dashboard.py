"""Portfolio overview backed by stored company facts and model predictions."""

from sentinel.tools import book_summaries, portfolio_alerts


def portfolio_dashboard(conn, horizon=3):
    if horizon not in (3, 6):
        raise ValueError("Horizon must be 3 or 6 months")
    book = {row["name"]: row for row in book_summaries(conn)}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.name, c.source, c.fetched_at, c.found_in_dealroom,
                   (c.found_in_dealroom AND c.source_endpoint = '/data/search') AS recorded_example,
                   p.model_score, p.next_stage, p.model_version, p.as_of,
                   p.months_since_last_vc, p.missing_features
            FROM company c LEFT JOIN prediction p
              ON p.company_id = c.id AND p.horizon_months = %s
            WHERE c.in_portfolio
            ORDER BY p.model_score DESC NULLS LAST, c.name
        """, (horizon,))
        companies = [{**book[row["name"]], **row} for row in cur.fetchall()]
        cur.execute("SELECT version, trained_at, metrics FROM model_run WHERE version IN (SELECT model_version FROM prediction) ORDER BY trained_at DESC LIMIT 1")
        model = cur.fetchone()
    return {"companies": companies, "alerts": portfolio_alerts(conn)["alerts"], "model": model, "horizon_months": horizon}
