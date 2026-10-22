import json
import pytest
from bonus_platform.engine.recruitment_source_preview import preview


def test_bounded_search_sheets_and_unknown_source(tmp_path):
    class Store:
        def read(self,month):return {'sources':[{'id':'known'}]}
        def _folder(self,month):return tmp_path
    (tmp_path/'parsed').mkdir()
    rows=[{'ref':{'sheet':'人员','row':i+3},'values':{'姓名':f'员工{i}','工号':f'zt{i:04d}','_internal':'hidden','金额':0}} for i in range(121)]
    rows.append({'ref':{'sheet':'第二表','row':5},'values':{'姓名':'第二表员工'}})
    path=tmp_path/'parsed/known.json';path.write_text(json.dumps({'sheets':[{'name':'人员'},{'name':'第二表'}],'records':rows}))
    before=path.read_bytes();store=Store()
    first=preview(store,202607,'known');assert len(first['rows'])==50 and first['pages']==3
    assert '_internal' not in first['columns'] and first['rows'][0]['values']['金额']==0
    last=preview(store,202607,'known',page=999);assert last['page']==3 and len(last['rows'])==21
    found=preview(store,202607,'known',query='ZT0007');assert found['total']==1 and found['rows'][0]['sourceRow']==10
    assert preview(store,202607,'known',sheet='第二表')['total']==1
    assert preview(store,202607,'known',query='missing')['rows']==[]
    with pytest.raises(ValueError):preview(store,202607,'../secret')
    with pytest.raises(ValueError):preview(store,202607,'known',sheet='不存在')
    assert path.read_bytes()==before
