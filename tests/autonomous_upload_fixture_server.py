"""Disposable UI regression fixture. No real company data or model calls."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.responses import JSONResponse
import uvicorn
from test_autonomous_workflow import setup


def build(root):
    root.mkdir(parents=True, exist_ok=True)
    scope = dict(tenant_id='upload-test', organization_id='upload-test',
                 legal_entity_id='上传交互测试企业', ledger_id='主账套',
                 accounting_period_id='2026-03', baseline_id='upload-test-march')
    app, service, sc, source, mature, result = setup.__wrapped__(root, scope)
    original_result = result()
    original_result['delivery']['findings'] = [{
        'id': 'business-1', 'title': '测试：补充业务说明',
        'detail': '此项仅用于验证说明草稿和提交交互。', 'needs_user': True,
        'affected_vouchers': [], 'evidence': [original_result['delivery']['entries'][0]['source']],
    }]
    service.autonomous.runner = lambda *args: original_result
    mature()
    service.autonomous.tick(sc)
    for worker in [service.autonomous, service.historical, service.payroll_mapping,
                   service.problem_review, service.material_agent, app.state.monthly_agent]:
        worker.start = lambda: None
    attempts = {}

    @app.middleware('http')
    async def observe(request, call_next):
        if request.method == 'POST':
            body = await request.json()
            record = {'path': request.url.path, 'filename': body.get('filename'),
                      'scope': body.get('scope'), 'object_id': body.get('object_id')}
            with (root/'requests.jsonl').open('a') as output:
                output.write(json.dumps(record, ensure_ascii=False)+'\n')
            if request.url.path == '/api/v1/artifacts':
                name = body['filename']
                attempts[name] = attempts.get(name, 0)+1
                await asyncio.sleep(.6)
                if name == '重试样例.txt' and attempts[name] == 1:
                    return JSONResponse(status_code=503, content={'error': {'message': '测试连接中断，请重试此文件'}})
            if request.url.path.startswith('/api/v1/autonomous/'):
                await asyncio.sleep(.8)
        return await call_next(request)
    return app


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--port', type=int, default=8776)
    args = p.parse_args()
    uvicorn.run(build(args.root), host='127.0.0.1', port=args.port)
