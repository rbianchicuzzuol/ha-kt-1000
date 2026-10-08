"""Canonical offline metadata; never copy cloud password/ticket fields into lists."""
import time

TYPES = {0:'multiple',1:'once',8:'clear_one',9:'clear_all'}

def seconds(value):
    if value in (None,''):return None
    value=int(value)
    return value//1000 if value>1000000000000 else value

def normalize(item, fallback=None):
    if not isinstance(item,dict):raise ValueError('Registro offline inválido.')
    fallback=fallback or {}
    def get(*names):
        for name in names:
            if item.get(name) is not None:return item[name]
        return None
    result={}
    mappings={'id':('id','password_id','offline_temp_password_id','pwd_id'),
        'name':('name','offline_temp_password_name','pwd_name'),
        'effective_time':('effective_time','gmt_start'),
        'invalid_time':('invalid_time','gmt_expired'),
        'create_time':('create_time','gmt_create'),
        'type':('pwd_type_code','type','pwd_type'),
        'status':('status',)}
    for key,names in mappings.items():
        value=get(*names)
        if value is None:value=fallback.get(key)
        if value is None:continue
        if key.endswith('_time'):value=seconds(value)
        elif key=='type':value=TYPES.get(value,TYPES.get(int(value),str(value)) if str(value).isdigit() else str(value))
        elif key=='status':value=int(value)
        else:value=str(value)
        result[key]=value
    if not result.get('id'):raise ValueError('A Tuya retornou registro offline sem ID.')
    return result

def creation_defaults(name,kind,start=None,end=None):
    hour=int(time.time())//3600*3600
    return {'name':name or 'Senha offline','type':TYPES[kind],
        'effective_time':hour if kind in (1,9) else seconds(start)//3600*3600 if start is not None else None,
        'invalid_time':hour+(6 if kind==1 else 24)*3600 if kind in (1,9) else seconds(end)//3600*3600 if end is not None else None,
        'create_time':int(time.time())}
