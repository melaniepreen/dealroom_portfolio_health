import numpy as np
from sentinel.real_model import snapshot, outcome, periods, split_for, month_id, FEATURES
from sentinel.normalize import funding_rounds


def round_at(year, month, stage, amount=1000000):
    return {'year':year,'month':month,'standardized_round':stage,'amount':amount}


def test_snapshot_never_uses_future_funding():
    rounds=[round_at(2020,1,'Seed'),round_at(2021,6,'Series A',8000000)]
    before=snapshot(rounds,month_id(2021,1))
    assert before[0]==1
    assert before[2]==12
    assert before[4]==1
    assert np.isclose(before[1],np.log1p(1000000))
    assert outcome(rounds,before,month_id(2021,1),6)==1
    assert outcome(rounds,before,month_id(2021,1),3)==0


def test_outcome_windows_do_not_cross_split_boundaries():
    assert max(periods('train'))+9 < min(periods('calibration'))
    assert max(periods('calibration'))+9 < min(periods('test'))
    assert max(periods('test'))+9 <= month_id(2026,9)


def test_unknown_stage_and_unknown_dates_cannot_make_training_rows():
    assert snapshot([round_at(2020,None,'Seed')],month_id(2021,1)) is None
    assert snapshot([round_at(2020,1,None)],month_id(2021,1)) is None
    parsed=funding_rounds([{'year':2020,'round':'Series A','is_vc_round':True}])[0]
    assert parsed['month'] is None
    assert parsed['standardized_round'] is None


def test_missing_amount_remains_missing_and_current_profile_excluded():
    vector=snapshot([round_at(2020,1,'Seed',None)],month_id(2021,1))
    assert np.isnan(vector[1]) and np.isnan(vector[5])
    assert 'prior_startup' not in FEATURES and 'university' not in FEATURES
    assert split_for('some-company') == split_for('some-company')
