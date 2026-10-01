"""Experimental funding-history model trained exclusively on live Dealroom records.

Company-disjoint train/calibration/test sets and chronological outcome windows.
Current founder profiles, current headcounts and synthetic panels are excluded.
"""
import hashlib
import json
import pickle
from datetime import date, datetime, timezone

import numpy as np
import xgboost as xgb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from sentinel.db import connect
from sentinel.features import venture_rounds
from sentinel.portfolio import STAGE_ORDER, next_stage

VERSION = 'xgboost-dealroom-live-v2'
FEATURES = ['stage', 'last_amount_log', 'months_since_last_vc', 'own_spacing', 'venture_round_count', 'total_amount_log']
DESCRIPTIONS = [
    'Last known standardised venture stage, ordered from Pre-Seed.',
    'Log of one plus last venture amount in USD; unknown stays missing.',
    'Months since the last venture round, excluding debt and grants.',
    'Median spacing between known venture rounds, in months.',
    'Number of venture rounds recorded by the snapshot date.',
    'Log of one plus total venture funding in USD; missing if any amount is unknown.',
]


def month_id(year, month):
    return year * 12 + month - 1


def snapshot(rounds, at):
    known = sorted([r for r in rounds if r.get('year') and r.get('month') and 1 <= r['month'] <= 12 and month_id(r['year'],r['month']) <= at], key=lambda r:(r['year'],r['month']))
    if not known or known[-1]['standardized_round'] not in STAGE_ORDER:
        return None
    last = known[-1]
    if next_stage(last['standardized_round']) is None:
        return None
    gaps = [month_id(b['year'],b['month'])-month_id(a['year'],a['month']) for a,b in zip(known,known[1:])]
    gaps = [g for g in gaps if g > 0]
    amount = last['amount']
    total = None if any(r['amount'] is None for r in known) else sum(r['amount'] for r in known)
    return [float(STAGE_ORDER.index(last['standardized_round'])), np.nan if amount is None else np.log1p(max(0,amount)), float(at-month_id(last['year'],last['month'])), float(np.median(gaps)) if gaps else np.nan, float(len(known)), np.nan if total is None else np.log1p(max(0,total))]


def outcome(rounds, vector, at, horizon):
    target = next_stage(STAGE_ORDER[int(vector[0])])
    return int(any(r.get('year') and r.get('month') and 1<=r['month']<=12 and at < month_id(r['year'],r['month']) <= at+horizon and r['standardized_round']==target for r in rounds))


def split_for(cid):
    bucket = int(hashlib.sha256(cid.encode()).hexdigest()[:8],16) % 10
    return 'train' if bucket < 6 else 'calibration' if bucket < 8 else 'test'


def periods(split):
    if split == 'train':
        return range(month_id(2018,1),month_id(2022,4),3)
    year = 2023 if split == 'calibration' else 2025
    return [month_id(year,m) for m in (1,4,7,10)]


def fit_and_score(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM company WHERE source='dealroom_live' AND found_in_dealroom AND NOT in_portfolio ORDER BY id")
        companies = list(cur.fetchall())
    histories = {c['id']:venture_rounds(conn,c['id']) for c in companies}
    models, metrics = {}, {'provenance':'Dealroom live API','experimental':True,'companies':len(companies),'features':FEATURES,'horizons':{},'split':'Disjoint companies: 60% train through Mar 2022; 20% calibration during 2023; 20% test during 2025. Latest training outcome precedes calibration; latest calibration outcome precedes testing.','limitations':['Bounded sample of UK venture-backed companies founded 2015–2022; not a representative population sample.','Current VC-backed/non-mature selection creates survivorship bias.','Uses funding history only; no historical founder or traction features.','Dealroom reporting gaps can turn unrecorded raises into negative labels.','API reports free tier; redacted records are rejected; missing amounts stay missing.','Several snapshots per company are correlated; metrics describe snapshots, not independent companies.']}
    for horizon in (3,6,9):
        sets = {k:[] for k in ('train','calibration','test')}
        stage_support = {}
        for c in companies:
            split = split_for(c['id'])
            rounds = histories[c['id']]
            for at in periods(split):
                v = snapshot(rounds,at)
                if v is None:
                    continue
                sets[split].append((v,outcome(rounds,v,at,horizon),c['id']))
                if split=='train':
                    stage_support.setdefault(int(v[0]),set()).add(c['id'])
        report = {'sets':{k:{'snapshots':len(rows),'positive':sum(r[1] for r in rows),'companies':len({r[2] for r in rows})} for k,rows in sets.items()},'published':False}
        metrics['horizons'][str(horizon)] = report
        training = sets['train']
        if len(training)<50 or sum(r[1] for r in training)<10 or len(training)-sum(r[1] for r in training)<10:
            report['trained']=False
            report['reason']='Insufficient positive/negative examples to fit the model.'
            continue
        arrays = {k:(np.array([r[0] for r in rows]),np.array([r[1] for r in rows])) for k,rows in sets.items()}
        x,y = arrays['train']
        classifier = xgb.XGBClassifier(n_estimators=100,max_depth=2,learning_rate=.04,min_child_weight=15,reg_lambda=10,subsample=.8,colsample_bytree=1,objective='binary:logistic',eval_metric='logloss',tree_method='hist',random_state=42,n_jobs=2)
        classifier.fit(x,y)
        booster = classifier.get_booster()
        report['trained'] = True
        report['feature_gains'] = {FEATURES[int(k[1:])]:float(v) for k,v in booster.get_score(importance_type='gain').items()}
        models[horizon] = {'booster':booster.save_raw(), 'calibrator':None, 'stage_support':{k:len(v) for k,v in stage_support.items()}}
        if any(len(rows)<50 or sum(r[1] for r in rows)<10 or len(rows)-sum(r[1] for r in rows)<10 for rows in (sets['calibration'],sets['test'])):
            report['reason']='Trained on real records, but too few next-stage outcomes for independent calibration/testing. Scores withheld.'
            continue
        cal_x,cal_y = arrays['calibration']
        margin = booster.predict(xgb.DMatrix(cal_x),output_margin=True)
        calibrator = LogisticRegression(C=1,random_state=42).fit(margin.reshape(-1,1),cal_y)
        test_x,test_y = arrays['test']
        raw = booster.predict(xgb.DMatrix(test_x),output_margin=True)
        scores = calibrator.predict_proba(raw.reshape(-1,1))[:,1]
        baseline = np.full(len(test_y),cal_y.mean())
        report.update(brier=float(brier_score_loss(test_y,scores)),baseline_brier=float(brier_score_loss(test_y,baseline)),average_precision=float(average_precision_score(test_y,scores)),test_prevalence=float(test_y.mean()),roc_auc=float(roc_auc_score(test_y,scores)),calibration_prevalence=float(cal_y.mean()),score_min=float(scores.min()),score_max=float(scores.max()),distinct_scores=int(len(np.unique(scores))))
        report['published'] = bool(report['brier']<report['baseline_brier'] and report['average_precision']>report['test_prevalence'] and calibrator.coef_[0,0]>0)
        report['reason'] = 'Experimental; passed held-out baseline checks.' if report['published'] else 'Held-out performance did not beat the prevalence baseline; portfolio scores withheld.'
        models[horizon] = {'booster':booster.save_raw(),'calibrator':calibrator,'stage_support':{k:len(v) for k,v in stage_support.items()}}
    with conn.cursor() as cur:
        cur.execute('INSERT INTO model_run(version,trained_at,device,metrics,payload) VALUES(%s,%s,%s,%s::jsonb,%s) ON CONFLICT(version) DO UPDATE SET trained_at=EXCLUDED.trained_at,metrics=EXCLUDED.metrics,payload=EXCLUDED.payload', (VERSION,datetime.now(timezone.utc),'cpu',json.dumps(metrics),pickle.dumps(models)))
        cur.execute('DELETE FROM prediction')
        cur.execute('SELECT * FROM company WHERE in_portfolio')
        holdings = list(cur.fetchall())
    today = datetime.now(timezone.utc).date()
    at = month_id(today.year,today.month)
    for c in holdings:
        rounds = venture_rounds(conn,c['id']) if c['source']=='dealroom_live' else []
        vector = snapshot(rounds,at)
        for horizon in (3,6,9):
            model = models.get(horizon)
            score,gains = None,{}
            reason = metrics['horizons'][str(horizon)]['reason']
            if vector is not None and model and metrics['horizons'][str(horizon)]['published']:
                if model['stage_support'].get(int(vector[0]),0)>=10:
                    booster = xgb.Booster();booster.load_model(bytearray(model['booster']))
                    margin = booster.predict(xgb.DMatrix(np.array([vector])),output_margin=True)
                    score = float(model['calibrator'].predict_proba(margin.reshape(-1,1))[0,1])
                    gains = {FEATURES[int(k[1:])]:float(v) for k,v in booster.get_score(importance_type='gain').items()}
                else:
                    reason='Insufficient training companies at this funding stage.'
            if c['hq_country'] != 'United Kingdom':
                score = None
                reason='Outside the UK training population; no validated estimate for this geography.'
            if vector is None:
                reason='No supported standardised venture stage in the live API funding history.'
            missing = [FEATURES[i] for i,v in enumerate(vector or []) if np.isnan(v)]
            if score is None:
                missing.append(reason)
            stage = STAGE_ORDER[int(vector[0])] if vector is not None else None
            with conn.cursor() as cur:
                cur.execute('INSERT INTO prediction(company_id,horizon_months,next_stage,model_score,months_since_last_vc,own_spacing,model_version,feature_gains,missing_features,as_of) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)',(c['id'],horizon,next_stage(stage),score,int(vector[2]) if vector else None,float(vector[3]) if vector and not np.isnan(vector[3]) else None,VERSION,json.dumps(gains),json.dumps(missing),today))
    conn.commit()
    return metrics


if __name__=='__main__':
    with connect() as conn:
        print(json.dumps(fit_and_score(conn),indent=2))
