from contextlib import nullcontext
from fastapi.testclient import TestClient
import sentinel.api as api


def test_dashboard_horizon_default_and_selection(monkeypatch):
    seen=[]
    monkeypatch.setattr(api,'connect',lambda:nullcontext(object()))
    def payload(conn,horizon):
        seen.append(horizon)
        return {'horizon_months':horizon}
    monkeypatch.setattr(api,'portfolio_dashboard',payload)
    client=TestClient(api.app)
    assert client.get('/portfolio').json()['horizon_months']==3
    assert client.get('/portfolio?horizon=6').json()['horizon_months']==6
    assert client.get('/portfolio?horizon=4').status_code==422
    assert seen==[3,6]
