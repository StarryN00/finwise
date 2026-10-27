"""Bounded arithmetic worker. No filesystem/network/database capabilities exposed."""
import ast
import collections
import datetime
import decimal
import itertools
import json
import math
import re
import resource
import sys
import types


def evaluate(payload):
    code = payload['code']
    if len(code) > 30000:
        raise ValueError('计算代码超过30000字符，请拆分步骤')
    tree = ast.parse(code)
    forbidden = (ast.ClassDef, ast.AsyncFunctionDef,
                 ast.Global, ast.Nonlocal, ast.With, ast.AsyncWith)
    for node in ast.walk(tree):
        if isinstance(node, forbidden):
            raise ValueError('计算工具不支持类、global/nonlocal或上下文管理器')
        if isinstance(node, ast.Name) and node.id.startswith('_') and node.id!='_':
            raise ValueError('不允许访问内部名称')
        if isinstance(node, ast.Attribute) and ((node.attr.startswith('_') and node.attr!='__name__') or node.attr.startswith(('gi_', 'cr_', 'ag_', 'f_', 'tb_'))):
            raise ValueError(f'不允许访问执行环境内部属性 {node.attr}（第{node.lineno}行）')
    safe = {name: getattr(__builtins__, name) if not isinstance(__builtins__, dict) else __builtins__[name]
            for name in ('abs','all','any','bool','dict','enumerate','filter','float','int','isinstance','len',
                         'list','map','max','min','next','range','reversed','round','set','sorted','str','sum',
                         'tuple','zip','type','format','repr','hasattr','Exception','ValueError','KeyError','TypeError')}
    modules={
        'decimal':types.SimpleNamespace(Decimal=decimal.Decimal,ROUND_HALF_UP=decimal.ROUND_HALF_UP),
        'collections':types.SimpleNamespace(Counter=collections.Counter,defaultdict=collections.defaultdict),
        'datetime':types.SimpleNamespace(datetime=datetime.datetime,date=datetime.date,timedelta=datetime.timedelta),
        'json':types.SimpleNamespace(loads=json.loads,dumps=json.dumps),
        'math':types.SimpleNamespace(**{n:getattr(math,n) for n in ('floor','ceil','sqrt','isfinite','isclose') }),
        'itertools':types.SimpleNamespace(combinations=itertools.combinations),
        're':types.SimpleNamespace(**{n:getattr(re,n) for n in ('search','match','fullmatch','findall','sub','split')})}
    def safe_import(name,globals=None,locals=None,fromlist=(),level=0):
        if level or name not in modules:raise ValueError('仅可导入受限的纯计算库：'+', '.join(modules))
        return modules[name]
    safe['__import__']=safe_import
    logs = []
    safe['print'] = lambda *args, **kw: logs.append(' '.join(str(a) for a in args)[:12000])
    namespace = {'__builtins__': safe, 'tables': payload['tables'], 'state': payload.get('state', {}),
                 'period': payload['period'], 'pdf': payload.get('pdf', {}),
                 'Decimal': decimal.Decimal, 'Counter': collections.Counter,
                 'defaultdict': collections.defaultdict, 'datetime': datetime.datetime, 'date': datetime.date,
                 're': types.SimpleNamespace(**{n: getattr(re,n) for n in ('search','match','fullmatch','findall','sub','split')}),
                 'combinations': itertools.combinations, 'result': None}
    namespace.update(modules)
    # Keep the already documented datetime/date callables available without importing.
    namespace['datetime']=datetime.datetime
    safe['globals']=lambda:dict(namespace)
    exec(compile(tree, '<monthly-calculation>', 'exec'), namespace)
    output = {'state': namespace['state'], 'result': namespace.get('result'), 'stdout': logs[-100:]}
    serialized = json.dumps(output, ensure_ascii=False, default=str, allow_nan=False)
    if len(serialized) > 3000000:
        raise ValueError('计算结果过大，请只保存结构化业务结果')
    return json.loads(serialized)


if __name__ == '__main__':
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    payload = json.loads(sys.stdin.read(8000000))
    # Imports and stdin are complete. Deny side effects even if the AST boundary is bypassed.
    def audit(event, args):
        if event in {'open', 'os.system', 'os.chdir', 'os.remove', 'os.rename', 'os.mkdir', 'os.putenv', 'os.fork'} or event.startswith(('socket.', 'subprocess.', 'ctypes.', 'shutil.')):
            raise PermissionError('计算工具不允许文件、进程或网络操作')
    sys.addaudithook(audit)
    try:
        print(json.dumps({'ok': True, **evaluate(payload)}, ensure_ascii=False, default=str, allow_nan=False))
    except Exception as exc:
        tb=exc.__traceback__;line=None
        while tb:
            if tb.tb_frame.f_code.co_filename=='<monthly-calculation>':line=tb.tb_lineno
            tb=tb.tb_next
        print(json.dumps({'ok': False, 'error': f'{type(exc).__name__}: {exc}'[:1800],'error_line':line}, ensure_ascii=False))
