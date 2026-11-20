import json
import re
import threading
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from pokerlab.solver.server import make_server

def test_loopback_api_origin_token_and_input_limits(tmp_path):
    server=make_server(8767,agent_dir=tmp_path/'agent');thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:8767'
    try:
        html=urlopen(base).read().decode();token=re.search('name="local-token" content="([^"]+)"',html).group(1)
        assert len(token)>30
        for headers in ({}, {'X-Pokerlab-Token':token,'Origin':'https://untrusted.invalid'}):
            req=Request(base+'/api/jobs',data=b'{}',headers={'Content-Type':'application/json',**headers})
            try:urlopen(req);assert False,'unauthorized request accepted'
            except HTTPError as e:assert e.code==400
        req=Request(base+'/api/jobs',data=b'{"kind":"not_real"}',headers={'Content-Type':'application/json','X-Pokerlab-Token':token})
        try:urlopen(req);assert False
        except HTTPError as e:assert e.code==400
        examples=json.load(urlopen(base+'/api/examples'))
        assert len(examples['flop_research.json']['board'])==3
        headers={'Content-Type':'application/json','X-Pokerlab-Token':token}
        value={'kind':'range','name':'API test range','value':'AA:0.5,AKs'}
        record=json.load(urlopen(Request(base+'/api/library',data=json.dumps(value).encode(),headers=headers)))
        library=json.load(urlopen(base+'/api/library'))
        assert any(r['id']==record['id'] and r['value']=='AA:0.5,AKs' for r in library)
        bad={'kind':'player','name':'invalid','value':[{'kind':'invented','strength':2,'streets':[3]}]}
        try:urlopen(Request(base+'/api/library',data=json.dumps(bad).encode(),headers=headers));assert False
        except HTTPError as e:assert e.code==400
    finally:server.shutdown();server.server_close();server.jobs.close();thread.join(timeout=5)
