"""Disposable HTTP fixture: real UI/API and source checks, deterministic analyst (no model calls)."""
import argparse
import base64
from io import BytesIO
from pathlib import Path
import sys
import time

import openpyxl
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.autonomous_checks import validate
from app.autonomous_runtime import prepare
from app.config import Settings
from app.review_loop import REVIEW_POLICY_VERSION
from app.main import create_app
from app.ontology.contracts import Scope, ArtifactInput


def build(root):
    root.mkdir(parents=True, exist_ok=True)
    app = create_app(Settings(root=ROOT, database_path=root/'review.db', storage_path=root/'sources',
                              require_auth=False, autonomous_enabled=True, agent_send_full_records=True))
    service = app.state.service
    scope = Scope(tenant_id='travel-test', organization_id='travel-test', legal_entity_id='差旅规则测试企业',
                  ledger_id='测试账套', accounting_period_id='2026-03', baseline_id='travel-march')
    service.create_scope(scope)
    book = openpyxl.Workbook(); book.active.title = 'Bank'
    book.active.append(['日期','摘要','收入','支出','收款人','报销人'])
    book.active.append(['2026-03-05','差旅费',0,990,'李甲','张乙'])
    book.active.append(['2026-03-06','差旅补贴',0,159.60,'张乙','张乙'])
    invoice = book.create_sheet('Invoices')
    invoice.append(['日期','项目','金额','税额','价税合计'])
    invoice.append(['2026-03-05','住宿',933.96,56.04,990])
    data = BytesIO(); book.save(data)
    source = service.create_artifact(ArtifactInput(scope=scope, filename='travel-fixture.xlsx',
                                    content_base64=base64.b64encode(data.getvalue()).decode()), actor_id='fixture')
    workflow = service.autonomous
    workflow.save_travel_policy(scope, 'fixture', 'operator', enabled=True, expected_version=0,
                                source_note='仅用于本地浏览器验收的模拟规则；没有真实企业业务')

    def analyst(folder, manifest, paths, context, settings, heartbeat, progress):
        sid = source['object_id']
        bank = {'source_id':sid,'sheet':'Bank','row':2}
        allowance = {**bank,'row':3}
        invoice = {'source_id':sid,'sheet':'Invoices','row':2}
        statements = context['statements']
        confirmation = next((a for a in statements if a['kind']=='FREE_TEXT' and '补贴159.60元' in a.get('text','')), None)
        policy = context['travel_policy']
        ready = ['候选001','候选002'] if confirmation else ['候选001']
        delivery = {'period':scope.accounting_period_id,'mode':'SOURCE_BOOKKEEPING','source_roles':{sid:'测试银行及住宿发票'},
                    'bindings':{},'opening':[], 'entries':[], 'findings':[], 'voucher_assessments':[],
                    'bank':[{'source':ref,'date':day,'income':'0.00','expense':amount} for ref,day,amount in
                            [(bank,'2026-03-05','990.00'),(allowance,'2026-03-06','159.60')]],
                    'invoices':[dict(source=invoice,date='2026-03-05',kind='进项',net='933.96',tax='56.04',gross='990.00')],
                    'report':'模拟分析器用于本地浏览器测试。住宿票款990元匹配，收款人与报销人均保留；补贴159.60元仍需人工确认，不因金额小放行。'*4}
        for number,day,amount,ref in [('候选001','2026-03-05','990.00',bank),('候选002','2026-03-06','159.60',allowance)]:
            for code,name,debit,credit in [('660202','管理费用—差旅费',amount,'0.00'),('1002','银行存款','0.00',amount)]:
                delivery['entries'].append(dict(voucher=number,date=day,code=code,name=name,memo='差旅测试',debit=debit,credit=credit,source=ref))
            delivery['voucher_assessments'].append(dict(voucher=number,status='READY_FOR_REVIEW' if number in ready else 'NEEDS_EVIDENCE',
                reason='普通差旅按已确认企业口径，票款匹配并通过账内查重' if number=='候选001' else '补贴金额与标准已确认' if confirmation else '补贴159.60元需确认适用标准',
                evidence=[ref],finding_ids=[] if number in ready else ['allowance']))
        if not confirmation:
            delivery['findings'] = [dict(id='allowance',title='补贴159.60元的标准待确认',detail='本笔为补贴；金额159.60元，需确认天数和企业标准。',
                needs_user=True,blocks_confirmation=True,affected_vouchers=['候选002'],evidence=[allowance],
                request=dict(question='补贴159.60元按什么标准计算？',why_needed='确认补贴金额和性质',can_continue='住宿990元已完成票款匹配',evidence_request='说明天数和企业标准',scope='PERIOD'),
                decision=dict(question='补贴计算标准是否已核实？',options=[],unavailable_reason='请先填写天数和企业补贴标准，系统再核对'))]
        delivery['settlement_matches'] = [dict(id='match1',payment_source=bank,invoice_sources=[invoice],basis='GROSS',status='MATCHED',
            other_components=[],affected_vouchers=['候选001'],finding_ids=[],reason='住宿价税合计990与差旅付款990一致，张乙报销由李甲收款，结算授权已核实；账内无重复')]
        delivery['travel_policy_applications'] = [dict(id='travel1',policy_id=policy['id'],policy_version=policy['version'],voucher='候选001',kind='TRAVEL',
            reason='收款人李甲、报销人张乙；仅姓名不同不阻断。住宿990元有票，银行备注差旅，账内无重复，按本企业差旅科目提出草稿。',
            evidence=[bank,invoice],settlement_match_ids=['match1'],manual_reasons=[],confirmed_reasons=[],finding_ids=[]),
            dict(id='allowance1',policy_id=policy['id'],policy_version=policy['version'],voucher='候选002',kind='ALLOWANCE',
            reason='补贴159.60元须逐笔人工确认，未设置自动金额限额。',evidence=[allowance],settlement_match_ids=[],
            manual_reasons=[] if confirmation else ['ALLOWANCE'], confirmed_reasons=[dict(code='ALLOWANCE',answer_ids=[confirmation['answer_id']])] if confirmation else [],
            finding_ids=[] if confirmation else ['allowance'])]
        delivery['decision_responses'] = [dict(answer_id=a['answer_id'],outcome='APPLIED' if confirmation else 'UNRESOLVED',
            explanation='已采用本次补贴标准说明，仍须人工复核凭证' if confirmation else '该说明没有明确补贴标准',affected_vouchers=['候选002']) for a in statements]
        workspace, pdf = prepare(folder, manifest, paths, context, settings)
        checked = validate(workspace, manifest, delivery, pdf, context)
        assert checked['passed'], checked['errors']
        return dict(delivery=delivery,mechanical=checked,review_policy_version=REVIEW_POLICY_VERSION,formal_balance_impact=False,
            review=dict(verdict='pass',defects=[],coverage=[dict(area='差旅模拟验收',evidence=[bank,invoice,allowance],conclusion='匹配和人工门禁通过')],
                ready_vouchers=ready,nonblocking_findings=[],reviewed_decisions=[] if confirmation else ['allowance'],reviewed_revisions=[],
                reviewed_responses=[a['answer_id'] for a in statements],reviewed_settlement_matches=['match1'],
                reviewed_travel_policy={k:policy[k] for k in ('id','version')},reviewed_travel_policy_applications=['travel1','allowance1']))

    workflow.runner = analyst
    job = workflow.current(scope); workflow._revise(scope, job, job['status'], {'queued_at':time.time()-6})
    assert workflow.tick(scope), workflow.current(scope)['data']['message']
    for worker in [service.historical,service.payroll_mapping,service.problem_review,service.material_agent,app.state.monthly_agent]:
        worker.start = lambda: None
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--port',type=int,default=8778)
    args = parser.parse_args()
    uvicorn.run(build(args.root),host='127.0.0.1',port=args.port)
