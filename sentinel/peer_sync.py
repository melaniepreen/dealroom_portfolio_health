"""Build isolated global peer benchmarks from live Dealroom histories."""
import json
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from urllib.parse import urlencode
from sentinel.dealroom import LiveDealroomProvider
from sentinel.normalize import traffic_points, filings, hq_country
from sentinel.portfolio import PORTFOLIO


def observations(provider, uuid):
    result = {}
    for metric, endpoint, parser, field in [('traffic','web-traffic',traffic_points,'traffic'),('employees','financials',filings,'employees')]:
        payload=provider.get(f'/data/companies/{uuid}/{endpoint}')
        rows=payload.get('data') or []
        points={}
        for row in parser(rows):
            value=row.get(field)
            if value is not None and math.isfinite(value) and value >= 0:
                # Annual employee observations retain year precision; never invent a month.
                date = str(row["year"]) if metric == "employees" else f"{row['year']:04d}-{row['month']:02d}"
                points[date]=value
        result[metric]=points
    return result


def aggregate(peers, own):
    result={}
    for metric in ('employees','traffic'):
        buckets=defaultdict(list)
        for peer in peers:
            for date,value in peer['observations'][metric].items():
                buckets[date].append(value)
        result[metric]=[{'date':date,'company':own[metric].get(date),'median':median(values) if len(values)>=5 else None,'count':len(values)} for date,values in sorted({date:buckets.get(date,[]) for date in set(buckets)|set(own[metric])}.items())]
    return result


def run(limit=40):
    provider=LiveDealroomProvider.from_env()
    output={}
    excluded={s['dealroom_uuid'] for s in PORTFOLIO}
    for spec in PORTFOLIO:
        body=provider.get('/data/companies/'+spec['dealroom_uuid'])['data']
        tags=body.get('taxonomy') or []
        industries=[t for t in tags if t['type']=='industry']
        stage=next((t for t in tags if t['type']=='growth_stage'),None)
        if not industries or not stage:
            output[spec['name']]={'status':'Sector or growth-stage classification unavailable; no defensible peer match.','peers':[],'series':{}}
            continue
        rows=[]
        for industry in industries:
            filt=f"and(taxonomy_id[in_any]:{industry['id']},growth_stage[in_any]:{stage['id']})"
            cursor=None
            target=max(5,limit//len(industries)); fetched=0
            while fetched<target:
                params={'limit':min(40,target-fetched),'filter':filt}
                if cursor: params['cursor']=cursor
                payload=provider.get('/data/companies?'+urlencode(params))
                batch=payload.get('data') or []
                rows.extend(batch); fetched+=len(batch)
                nxt=(payload.get('page') or {}).get('next_cursor')
                if not nxt or nxt==cursor or not batch: break
                cursor=nxt
        unique={r['uuid']:r for r in rows if not r.get('locked') and r.get('uuid') not in excluded}
        def fetch(row):
            try:
                return {'name':row['name'],'uuid':row['uuid'],'country':hq_country(row),'observations':observations(provider,row['uuid'])}
            except Exception as exc:
                return {'name':row['name'],'uuid':row['uuid'],'error':type(exc).__name__}
        with ThreadPoolExecutor(max_workers=4) as pool: records=list(pool.map(fetch,unique.values()))
        peers=[r for r in records if 'observations' in r]
        own=observations(provider,spec['dealroom_uuid'])
        series=aggregate(peers,own)
        output[spec['name']]={'scope':'Global','match':' / '.join(t['name'] for t in industries)+' · '+stage['name'],'status':'Global industry and current growth-stage peers; a bounded sample, not a direct-competitor census.','peers':[{k:v for k,v in p.items() if k!='observations'} for p in records],'series':series,'fetched_at':datetime.now(timezone.utc).isoformat()}
        print(spec['name'],len(peers),'peers;', {k:sum(r['median'] is not None for r in v) for k,v in series.items()},flush=True)
    path=Path(__file__).parent/'static'/'peers.json'
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(output));temp.replace(path)

if __name__=='__main__':run()
