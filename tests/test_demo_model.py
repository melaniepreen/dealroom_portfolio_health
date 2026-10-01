import json
from pathlib import Path
import numpy as np
import xgboost as xgb
from sentinel.demo_model import FEATURES


def test_demo_scores_and_explanations_match_saved_xgboost_models():
    root=Path(__file__).resolve().parents[1]/'sentinel'/'static'
    payload=json.loads((root/'demo.json').read_text())
    assert payload['synthetic'] is True
    vector=np.array([[payload['model_inputs'][name] for name in FEATURES]])
    for horizon,report in payload['horizons'].items():
        booster=xgb.Booster()
        booster.load_model(root/f'demo-model-{horizon}.json')
        actual=float(booster.predict(xgb.DMatrix(vector))[0])
        assert np.isclose(actual,report['score'])
        logit=report['base_margin']+sum(r['contribution'] for r in report['evidence'])
        assert np.isclose(1/(1+np.exp(-logit)),actual,atol=1e-6)
