"""Opt-in live integration check using synthetic files and a disposable ledger."""
import argparse
import base64
from dataclasses import replace
from io import BytesIO
from decimal import Decimal
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import openpyxl
from app.config import Settings
from app.main import create_app
from app.ontology.contracts import Scope,ArtifactInput


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--backend',choices=['codex','claude_code'],default='claude_code')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execution-mode',choices=['local','docker'],default='local')
    parser.add_argument('--host-run-root',type=Path,help='宿主机映射任务目录；在应用容器内验收时指定')
    args=parser.parse_args()
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
    if (root/'test.db').exists():raise SystemExit('请使用新的验收目录，避免复用旧结果')
    settings=replace(Settings.from_env(ROOT),database_path=root/'test.db',storage_path=root/'sources',
        autonomous_enabled=True,autonomous_backend=args.backend,autonomous_execution_mode=args.execution_mode,
        autonomous_host_run_root=str(args.host_run_root or root/'autonomous-runs'),require_auth=False,environment='development',
        agent_mode='disabled',agent_loop_enabled=False,monthly_agent_enabled=False,agent_send_full_records=True)
    service=create_app(settings).state.service
    scope=Scope(tenant_id='executor-verification',organization_id='executor-verification',legal_entity_id='合成验收企业',
        ledger_id='test',accounting_period_id='2026-08',baseline_id='test-august')
    service.create_scope(scope)
    book=openpyxl.Workbook();sheet=book.active;sheet.title='银行流水'
    sheet.append(['日期','摘要','收入','支出','余额','银行','对方户名'])
    sheet.append(['2026-08-03','银行账户手续费',0,10,490,'合成验收银行','合成验收银行'])
    data=BytesIO();book.save(data)
    service.create_artifact(ArtifactInput(scope=scope,filename='synthetic-bank-fee.xlsx',content_base64=base64.b64encode(data.getvalue()).decode()),actor_id='executor-tester')
    workflow=service.autonomous;job=workflow.current(scope)
    workflow._revise(scope,job,job['status'],{'queued_at':time.time()-6})
    passed=workflow.tick(scope)
    view=workflow.project(scope)
    (root/'workbench.json').write_text(json.dumps(view,ensure_ascii=False,indent=2))
    job=workflow.current(scope)
    vouchers=view.get('vouchers',[])
    original_amount_verified=(len(vouchers)==1 and vouchers[0]['status']=='DRAFT' and
        vouchers[0]['data']['date']=='2026-08-03' and
        Decimal(vouchers[0]['data']['debit_total'])==Decimal(vouchers[0]['data']['credit_total'])==Decimal('10.00'))
    summary={'synthetic':True,'backend':args.backend,'execution_mode':args.execution_mode,'run_id':job['object_id'],
        'status':job['status'],'message':job['data']['message'],'ready_count':view['autonomous_workflow']['ready_count'],
        'original_amount_verified':original_amount_verified,'formal_posting':False,'database':str(root/'test.db')}
    (root/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False))
    if not passed or not original_amount_verified:raise SystemExit(1)


if __name__=='__main__':main()
