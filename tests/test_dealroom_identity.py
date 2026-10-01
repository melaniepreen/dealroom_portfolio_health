from sentinel.dealroom import LiveDealroomProvider


def test_same_name_requires_domain_disambiguation():
    p=LiveDealroomProvider('test','test')
    p.get=lambda path:{'data':[{'name':'Catalog','type':'company','uuid':'wrong','website_domain':'getcatalog.ai'},{'name':'Catalog','type':'company','uuid':'right','website_domain':'startcatalog.com'}]}
    assert p.search_company('Catalog') is None
    assert p.search_company('Catalog','startcatalog.com')['uuid']=='right'
    assert p.search_company('Catalog','different.com') is None


def test_round_pagination_uses_cursor_parameter():
    p=LiveDealroomProvider('test','test')
    calls=[]
    def response(path):
        calls.append(path)
        return {'data':[{'id':len(calls)}], 'page':{'next_cursor':'next-page' if len(calls)==1 else None}}
    p.get=response
    assert len(p.funding_history('id'))==2
    assert 'cursor=next-page' in calls[1]
