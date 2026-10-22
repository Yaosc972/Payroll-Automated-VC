"""Read-only, bounded pages of existing parsed source records."""
import json


def preview(store, month, source_id, sheet='', query='', page=1):
    state=store.read(month)
    source=next((s for s in state['sources'] if s['id']==source_id),None)
    if not source:raise ValueError('来源文件不存在')
    path=store._folder(month)/'parsed'/f"{source['id']}.json"
    if not path.is_file():raise ValueError('该资料暂无可预览的解析数据，请下载原件查看')
    data=json.loads(path.read_text())
    sheets=[s['name'] for s in data.get('sheets',[])]
    if sheet and sheet not in sheets:raise ValueError('工作表不存在')
    sheet=sheet or next(iter(sheets),'')
    records=[r for r in data.get('records',[]) if r.get('ref',{}).get('sheet','')==sheet]
    fields=list(dict.fromkeys(k for r in records for k in r.get('values',{}) if not k.startswith('_')))
    first=[k for k in ('姓名','工号','入职日期','职位','录用岗位') if k in fields]
    fields=first+[k for k in fields if k not in first]
    needle=query.strip().casefold()
    if needle:records=[r for r in records if any(needle in str(r.get('values',{}).get(k,'')).casefold() for k in fields)]
    total=len(records);pages=max(1,(total+49)//50);page=min(max(1,page),pages)
    return {'sheet':sheet,'sheets':sheets,'columns':fields,'total':total,'page':page,'pages':pages,
            'rows':[{'sourceRow':r.get('ref',{}).get('row'),'values':{k:r.get('values',{}).get(k,'') for k in fields}}
                    for r in records[(page-1)*50:page*50]]}
