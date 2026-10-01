from sentinel.peer_sync import aggregate


def test_peer_medians_require_five_observations_and_keep_company_only_dates():
    peers=[{'observations':{'employees':{'2025':i},'traffic':{}}} for i in range(5)]
    result=aggregate(peers,{'employees':{'2024':12,'2025':8},'traffic':{}})
    assert result['employees']==[{'date':'2024','company':12,'median':None,'count':0},{'date':'2025','company':8,'median':2,'count':5}]
    assert aggregate(peers[:4],{'employees':{},'traffic':{}})['employees'][0]['median'] is None
