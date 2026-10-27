"""Isolated browser fixture with real source validation and deterministic analysis."""
import argparse
import base64
from io import BytesIO
from pathlib import Path
import sys
import time
import openpyxl
import uvicorn

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.main import create_app
from app.ontology.contracts import Scope, ArtifactInput
from app.autonomous_runtime import prepare
from app.autonomous_checks import validate
from app.review_loop import REVIEW_POLICY_VERSION
from test_invoice_matching import matching_result


def build(root):
    app=create_app(Settings(root=ROOT,database_path=root/'db.sqlite',storage_path=root/'sources',
                            require_auth=False,autonomous_enabled=True,agent_send_full_records=True))
    service=app.state.service
    scope=Scope(tenant_id='matching-test',organization_id='matching-test',legal_entity_id='票款核对测试企业',
                ledger_id='测试账套',accounting_period_id='2026-03',baseline_id='matching-march')
    service.create_scope(scope)
    book=openpyxl.Workbook();book.active.title='Bank';book.active.append(['日期','摘要','收入','支出','收款人'])
    for amount in (266,100,50):book.active.append(['2026-03-01','差旅费',0,amount,'张三' if amount!=50 else '李四'])
    invoices=book.create_sheet('Invoices');invoices.append(['日期','票号','金额','税额','价税合计'])
    for i,amount in enumerate((123,117),1):invoices.append(['2026-02-28',f'票{i}',amount,0,amount])
    stream=BytesIO();book.save(stream)
    source=service.create_artifact(ArtifactInput(scope=scope,filename='matching-fixture.xlsx',content_base64=base64.b64encode(stream.getvalue()).decode()),actor_id='fixture')
    def analyst(folder,manifest,paths,context,settings,heartbeat,progress):
        def base():return dict(review_policy_version=REVIEW_POLICY_VERSION,formal_balance_impact=False,
            delivery=dict(period=scope.accounting_period_id,mode='SOURCE_BOOKKEEPING',source_roles={source['object_id']:'模拟银行与车票'},bindings={},opening=[],report='模拟资料，仅用于票款集中核对交互验收。'*12),
            review=dict(verdict='pass',defects=[],coverage=[dict(area='模拟票款',evidence=[{'source_id':source['object_id'],'sheet':'Bank','row':2}],conclusion='已校验模拟资料')],reviewed_revisions=[]))
        r=matching_result(base,source,context['statements']);d=r['delivery']
        # A ready, independent payment remains reviewable throughout the matching task.
        ref={'source_id':source['object_id'],'sheet':'Bank','row':4}
        d['bank'].append(dict(source=ref,date='2026-03-01',income='0.00',expense='50.00',counterparty='李四',memo='预付款'))
        for code,name,debit,credit in [('1123','预付账款','50.00','0.00'),('1002','银行存款','0.00','50.00')]:
            d['entries'].append(dict(voucher='候选003',date='2026-03-01',code=code,name=name,memo='预付款',debit=debit,credit=credit,source=ref))
        d['voucher_assessments'].append(dict(voucher='候选003',status='READY_FOR_REVIEW',reason='供应商预付款已有依据，无需跟进交付',finding_ids=[],evidence=[ref]))
        r['review']['ready_vouchers']=['候选003']
        selected=next((a for a in context['statements'] if a.get('invoice_selection',{}).get('action')=='CONFIRM_INVOICES'),None)
        if selected:
            item=d['findings'][0]['invoice_matching']
            refs=[i['source'] for i in selected['invoice_selection']['invoices']]
            item.update(state='AMOUNT_DIFFERENCE',confirmed_invoice_sources=refs,candidate_invoice_sources=[],answer_ids=[selected['answer_id']])
            item['reason']='已确认两张车票属于本笔；剩余26元性质未知，不猜成补贴'
        workspace,_=prepare(folder,manifest,paths,context,settings)
        checked=validate(workspace,manifest,d,{},context)
        assert checked['passed'],checked['errors']
        r['mechanical']=checked
        return r
    w=service.autonomous;w.runner=analyst
    job=w.current(scope);w._revise(scope,job,job['status'],{'queued_at':time.time()-6})
    assert w.tick(scope),w.current(scope)['data']['message']
    for worker in [service.historical,service.payroll_mapping,service.problem_review,service.material_agent,app.state.monthly_agent]:
        worker.start=lambda:None
    return app


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,default=8778)
    a=p.parse_args();a.root.mkdir(parents=True,exist_ok=True)
    uvicorn.run(build(a.root),host='127.0.0.1',port=a.port)
