"""Read-only local acceptance runner for the Juxianda source directory.

The script copies bytes into a temporary FinWise scope and removes that scope
when it exits. It never writes to the shared source directory and never calls
an external model or external accounting system.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
import tempfile
import re

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.main import create_app
from app.ontology.contracts import ArtifactInput, Scope
from app.ontology.errors import DomainError


DEFAULT_ROOT = Path("/Volumes/共享文件夹/财务项目/聚贤达/3/聚贤达/聚贤达3月材料")
SUPPORTED = {
    "聚贤达26年3月进项.xlsx": "purchase_invoices",
    "聚贤达26年3月销项.xlsx": "sales_invoices",
    "2026.3月聚贤达农业银行流水-账户明细查询列表.xls": "bank_statement",
    "2026.3月聚贤达农村商业银行流水.xls": "bank_statement",
    "2026.3月聚贤达南京银行流水.xls": "bank_statement",
    "2026.3月聚贤达泰隆银行流水.xls": "bank_statement",
    "2026.3月聚贤达工资表.xls": "payroll",
    "2026.3月聚贤达社保人员明细月缴费明细.xlsx": "social_security",
    "2026.3月聚贤达公积金缴费明细.xls": "housing_fund",
    "2026.3月农村商业银行电子承兑明细.xls": "electronic_acceptance",
    "2026.2月南京应收、应付电子承兑.xls": "electronic_acceptance",
    "昆山聚贤达精密模具有限公司_综合所得申报_202603.xls": "individual_income_tax",
}


def observed_period(filename: str) -> str:
    """Infer only an explicit file-name period; unknown is intentionally out of scope."""
    match = re.search(r"(20\d{2})(\d{2})", filename)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    match = re.search(r"(20\d{2})[.\-_年](\d{1,2})月", filename)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    match = re.search(r"(?<!\d)(\d{2})年(\d{1,2})月", filename)
    if match:
        return f"20{match.group(1)}-{int(match.group(2)):02d}"
    return "UNKNOWN"


def run(source_root: Path) -> dict:
    if not source_root.is_dir():
        raise SystemExit(f"资料目录不存在：{source_root}")
    scope = Scope(tenant_id="juxianda-test", organization_id="kunshan-juxianda", legal_entity_id="kunshan-juxianda", ledger_id="chengyuan-ledger", accounting_period_id="2026-03", baseline_id="baseline-2026-03")
    with tempfile.TemporaryDirectory(prefix="finwise-juxianda-") as temporary:
        settings = Settings(root=Path(__file__).resolve().parents[1], database_path=Path(temporary) / "run.db", storage_path=Path(temporary) / "artifacts", require_auth=False)
        app = create_app(settings)
        service = app.state.service
        service.create_scope(scope, actor_id="juxianda-test")
        files = []
        for source in sorted(source_root.iterdir()):
            artifact = service.create_artifact(ArtifactInput(scope=scope, filename=source.name, content_base64=base64.b64encode(source.read_bytes()).decode(), observed_period=observed_period(source.name)), actor_id="juxianda-test")
            kind = SUPPORTED.get(source.name)
            item = {"file": source.name, "artifact": artifact["object_id"], "artifact_status": artifact["status"], "observed_period": observed_period(source.name), "kind": kind or "RECEIVED_ONLY"}
            if kind and item["observed_period"] not in {"UNKNOWN", scope.accounting_period_id}:
                item.update({"parse_status": "SKIPPED_PERIOD_EXCEPTION", "counts": {"rows": 0, "parsed": 0, "needs_review": 0, "period_exception": 0}, "errors": ["原件期间与当前工作期间不一致，按门禁保留待处理"]})
            elif kind:
                effect = service.execute_command(scope, action="parse_artifact", target_id=artifact["object_id"], target_version=artifact["version"], idempotency_key="juxianda-parse-" + artifact["object_id"], actor_id="juxianda-test", role="accountant", payload={"document_kind": kind, **({"bank_account_ref": "juxianda-bank-" + source.stem} if kind == "bank_statement" else {})})["effect"]
                item.update({"parse_status": effect["artifact"]["data"].get("parse_status"), "counts": effect["counts"], "errors": effect["errors"], "sheets": effect["sheets"]})
            files.append(item)
        facts = service.store.list_objects("FactRecord", scope)
        invoices = [item for item in facts if item["data"].get("record_type") == "INVOICE"]
        payments = [item for item in facts if item["data"].get("record_type") == "PAYMENT"]
        ready_invoices = [item for item in invoices if item["status"] == "PARSED"]
        ready_payments = [item for item in payments if item["status"] == "PARSED"]
        procurement_gate = {
            "status": "BLOCKED",
            "reason": "当前没有同时满足 PARSED 的进项发票和付款事实，未进入采购处理组；待复核事实不能被强行放行",
            "invoice_candidates": len(invoices),
            "invoice_ready": len(ready_invoices),
            "payment_candidates": len(payments),
            "payment_ready": len(ready_payments),
            "missing_evidence": ["CONTRACT", "STOCK_IN"],
        }
        if ready_invoices and ready_payments:
            try:
                group = service.create_procurement_business(scope, fact_ids=[ready_invoices[0]["object_id"], ready_payments[0]["object_id"]], business_identity="juxianda-real-source-001", actor_id="juxianda-test")
                procurement_gate.update({"status": "CANDIDATE_BLOCKED", "group_id": group["object_id"], "missing_evidence": group["data"].get("missing_evidence", [])})
            except DomainError as exc:
                procurement_gate.update({"reason": str(exc)})
        return {"scope": scope.model_dump(), "files": files, "procurement_gate": procurement_gate, "artifact_count": len(service.store.list_objects("SourceArtifact", scope)), "fact_count": len(facts)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="在临时 Scope 中只读验收聚贤达三月资料")
    parser.add_argument("source_root", nargs="?", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    print(json.dumps(run(args.source_root), ensure_ascii=False, indent=2))
