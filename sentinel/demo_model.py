"""Isolated synthetic XGBoost demonstration; never writes live database rows."""
import json
from pathlib import Path
import numpy as np
import xgboost as xgb
from sklearn.metrics import brier_score_loss

FEATURES = ['months_since_round','revenue_growth','paid_pilots','technical_milestone','runway_months']
LABELS = ['Time since last round','Annual revenue growth','Paid pilot customers','Technical milestone complete','Cash runway']


def build():
    rng=np.random.default_rng(42)
    n=2400
    x=np.column_stack([rng.uniform(3,30,n),rng.uniform(-.2,2,n),rng.integers(0,7,n),rng.integers(0,2,n),rng.uniform(3,24,n)])
    # Explicit simulation assumptions, not empirical venture-funding relationships.
    propensity=-4.8+.08*x[:,0]+1.25*x[:,1]+.38*x[:,2]+1.1*x[:,3]-.06*x[:,4]
    latent=rng.uniform(size=n)
    company=np.array([[24,1.8,6,1,9]],dtype=float)
    output={'name':'Asterion Quantum','industry':'Deep technology · Quantum photonics','series':'Seed','next_stage':'Series A','last_venture_round':'Oct 2024','as_of':'2026-10-01','synthetic':True,'model_version':'xgboost-synthetic-demo-v1','training_rows':1800,'test_rows':600,'horizons':{}}
    for horizon,offset in [(3,0),(6,.9)]:
        y=(latent < 1/(1+np.exp(-(propensity+offset)))).astype(int)
        model=xgb.XGBClassifier(n_estimators=120,max_depth=3,learning_rate=.055,min_child_weight=8,reg_lambda=4,random_state=42,n_jobs=2,eval_metric='logloss')
        model.fit(x[:1800],y[:1800])
        booster=model.get_booster()
        contributions=booster.predict(xgb.DMatrix(company),pred_contribs=True)[0]
        score=float(model.predict_proba(company)[0,1])
        vals=['24 months','180%','6 customers','Completed','9 months']
        evidence=[{'feature':f,'label':label,'value':val,'contribution':float(contributions[i])} for i,(f,label,val) in enumerate(zip(FEATURES,LABELS,vals))]
        evidence.sort(key=lambda row:row['contribution'],reverse=True)
        output['horizons'][str(horizon)]={'score':score,'evidence':evidence,'brier_synthetic_test':float(brier_score_loss(y[1800:],model.predict_proba(x[1800:])[:,1])),'base_margin':float(contributions[-1])}
        model.save_model(Path(__file__).parent/'static'/f'demo-model-{horizon}.json')
    (Path(__file__).parent/'static'/'demo.json').write_text(json.dumps(output,indent=2))
    return output


if __name__=='__main__':
    data=build()
    print({h:round(r['score'],4) for h,r in data['horizons'].items()})
