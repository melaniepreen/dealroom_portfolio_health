"""Bounded live API cohort import; never mixes fixtures into model training."""
import json
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from sentinel.db import connect, init_schema
from sentinel.dealroom import LiveDealroomProvider
from sentinel.normalize import hq_country
from sentinel.portfolio import PORTFOLIO
from sentinel.store import apply_dealroom_record, company_id


def industry(body):
    return next((r['name'] for r in body.get('taxonomy', []) if r.get('type') == 'industry'), 'Unknown')


def run(per_year=40):
    provider = LiveDealroomProvider.from_env()
    records, holdings, manifest = [], [], {'cohorts': [], 'missing_holdings': []}
    seen = set()
    for spec in PORTFOLIO:
        match = provider.search_company(spec['name'], spec.get('domain'))
        if not match:
            manifest['missing_holdings'].append(spec['name'])
            print('No exact API match:', spec['name'], flush=True)
            continue
        if spec.get('dealroom_uuid') and match['uuid'] != spec['dealroom_uuid']:
            raise RuntimeError(f"Dealroom identity changed for {spec['name']}; import stopped.")
        record = provider.company_record(match['uuid'])
        body = record['company']
        if body.get('locked'):
            raise RuntimeError(f"Restricted company record: {spec['name']}")
        seen.add(match['uuid'])
        holdings.append(({**spec, 'industry': industry(body), 'in_portfolio': True}, record, match['uuid']))
        print('Portfolio fetched:', spec['name'], len(record['rounds']), 'rounds', flush=True)
    # A bounded sample across founding cohorts, with no filtering on future raises.
    for year in range(2015, 2023):
        filt = f'and(hq_location[eq]:93,classification[in_any]:vc_backed,growth_stage[nin_any]:412,taxonomy_id[nin_any]:1102801,launch_date[gte]:{year},launch_date[lt]:{year+1})'
        rows, cursor = [], None
        while len(rows) < per_year:
            params = {'limit': min(40, per_year-len(rows)), 'filter': filt, 'include_total': 'true'}
            if cursor:
                params['cursor'] = cursor
            payload = provider.get('/data/companies?' + urllib.parse.urlencode(params))
            batch = payload.get('data') or []
            if any(row.get('locked') for row in batch):
                raise RuntimeError('The cohort contains tier-redacted records; training stopped.')
            rows.extend(batch)
            nxt = (payload.get('page') or {}).get('next_cursor')
            if not nxt or not batch:
                break
            if nxt == cursor:
                raise RuntimeError('Company pagination did not advance')
            cursor = nxt
        manifest['cohorts'].append({'year': year, 'sample':len(rows), 'page':payload.get('page'), 'filter':filt})
        rows = [body for body in rows if body['uuid'] not in seen and hq_country(body) == 'United Kingdom']
        with ThreadPoolExecutor(max_workers=4) as pool:
            histories = list(pool.map(lambda body: provider.funding_history(body['uuid']), rows))
        for body, rounds in zip(rows, histories):
            records.append(({'name':body['name'], 'industry':industry(body), 'in_portfolio':False}, {'company':body,'rounds':rounds}, body['uuid']))
            seen.add(body['uuid'])
        print('Training cohort', year, 'complete;', len(records), 'companies fetched', flush=True)
    if not records:
        raise RuntimeError('No real training records fetched; database left unchanged.')
    # The existing store keys companies by name, so account for name collisions
    # explicitly instead of overstating the number of independent companies.
    manifest['sampled_training_records'] = len(records)
    records = list({company_id(spec['name']): (spec, record, uuid)
                    for spec, record, uuid in records
                    if spec['name'].casefold() not in {s['name'].casefold() for s in PORTFOLIO}}.values())
    manifest['duplicate_or_holding_names_excluded'] = manifest['sampled_training_records'] - len(records)
    fetched = datetime.now(timezone.utc)
    manifest.update(fetched_at=fetched.isoformat(), training_companies=len(records), portfolio_companies=len(holdings), provenance='Dealroom API', restrictions='API page reports free tier; no locked records accepted. Missing amounts remain missing.')
    Path('.dealroom-cache/live-manifest.json').write_text(json.dumps(manifest, indent=2))
    with connect() as conn:
        init_schema(conn)
        # Preserve a recoverable snapshot before replacing demonstration rows.
        tables = ['company','funding_event','monthly_signal','filing','industry_month','founder','fund_target','prediction','alert','passage']
        backup = {}
        with conn.cursor() as cur:
            for table in tables:
                cur.execute('SELECT * FROM ' + table)
                backup[table] = cur.fetchall()
        backup_path = Path('.dealroom-cache') / ('before-live-' + fetched.strftime('%Y%m%dT%H%M%S') + '.json')
        backup_path.write_text(json.dumps(backup, default=str))
        for spec, record, uuid in holdings + records:
            # Never backfill a live stage from the old example portfolio labels.
            spec = {k:v for k,v in spec.items() if k != 'stage_tag'}
            apply_dealroom_record(conn, spec, record, fetched)
            with conn.cursor() as cur:
                cur.execute('UPDATE company SET source=%s, source_endpoint=%s, in_portfolio=%s WHERE id=%s', ('dealroom_live', f'/data/companies/{uuid}', spec['in_portfolio'], company_id(spec['name'])))
        with conn.cursor() as cur:
            # Remove only the identifiable generated panel after backing it up.
            cur.execute("DELETE FROM company WHERE id LIKE 'panel-%%' AND source='dealroom' AND NOT in_portfolio")
            cur.execute("DELETE FROM industry_month WHERE source='dealroom'")
            cur.execute("DELETE FROM prediction")
            cur.execute("DELETE FROM alert")
            # The fixture's one fund target is not an investor-entered target.
            if any(r['id']=='nila' and r['source_endpoint']=='/data/search' for r in backup['company']):
                cur.execute("DELETE FROM fund_target WHERE company_id='nila' AND metric='employees' AND target_value=12 AND period='2026'")
            for name in manifest['missing_holdings']:
                cid = company_id(name)
                for table in ['funding_event','monthly_signal','filing','founder','passage']:
                    cur.execute('DELETE FROM '+table+' WHERE company_id=%s', (cid,))
                cur.execute("UPDATE company SET found_in_dealroom=FALSE,stage=NULL,source='dealroom_live',fetched_at=%s WHERE id=%s", (fetched,cid))
        conn.commit()
    print(json.dumps(manifest, default=str), flush=True)


if __name__ == '__main__':
    run()
