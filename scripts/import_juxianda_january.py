"""Rebuild a fresh January Staging dataset from explicitly selected originals.

The former dataset and source directory are read-only. No model, approval,
grouping, voucher, or delivery command is run. Back up the former dataset
before switching the running server to the new database.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import grant_scope
from app.config import Settings
from app.db import utcnow
from app.main import create_app
from app.ontology.contracts import ArtifactInput, Scope


PROJECT = Path(__file__).resolve().parents[1]
ACTOR = "juxianda-january-import"
USER = "juxianda-staging"
SCOPE = Scope(tenant_id="juxianda-test", organization_id="kunshan-juxianda",
              legal_entity_id="kunshan-juxianda", ledger_id="chengyuan-ledger",
              accounting_period_id="2026-01", baseline_id="baseline-2026-01")
HISTORY = ["序时账_2025年01月至2025年12月.xls", "余额表_2025年01月至2025年12月.xls"]
JANUARY = {
    "聚贤达1月进项.xlsx": "purchase_invoices",
    "聚贤达1月销项.xlsx": "sales_invoices",
    "2026.1月聚贤达农业银行流水.xls": "bank_statement",
    "2026.1月聚贤达南京银行流水.xls": "bank_statement",
    "2026.1月聚贤达泰隆银行流水.xls": "bank_statement",
    "2026.1月聚贤达泰隆银行保证金流水.xls": "bank_statement",
    "2026.1月聚贤达中国银行流水.pdf": "bank_statement",
    "2026.1月聚贤达工资表.xls": "payroll",
    "2026.1月聚贤达社保人员月缴费明细.xlsx": "social_security",
    "2026.1月聚贤达医保单位缴费明细.xls": "social_security",
    "2026.1月聚贤达南京银行应收电子承兑明细表.xls": "electronic_acceptance",
    "2026.1月聚贤达泰隆银行应收电子承兑明细表.xls": "electronic_acceptance",
    "2026.1月聚贤达泰隆银行应付电子承兑明细表.xls": "electronic_acceptance",
    "2026.1月聚贤达泰隆银行应付银行申请电子承兑明细表.xls": "electronic_acceptance",
    "2026.1月+2月聚贤达公积金单位缴费明细.xls": None,
}


def source_manifest(source_root: Path) -> list[dict]:
    """Whitelist files, retain bytes, and never traverse another month folder."""
    source_root = source_root.resolve(strict=True)
    items = []
    selections = [(name, "historical_reference", "2025-12", None) for name in HISTORY]
    selections += [("聚贤达1月材料/" + name, "business",
                    "2026-01~2026-02" if "1月+2月" in name else "2026-01", kind)
                   for name, kind in JANUARY.items()]
    for relative, purpose, period, kind in selections:
        path = (source_root / relative).resolve(strict=True)
        if path != source_root / relative:
            raise ValueError("白名单原件或月份目录不能使用符号链接重定向")
        if not path.is_relative_to(source_root) or not path.is_file():
            raise ValueError("原件不在指定资料目录内")
        content = path.read_bytes()
        if not content or len(content) > 16 * 1024 * 1024:
            raise ValueError(f"原件为空或超过导入限制：{relative}")
        items.append({"source_path": str(path), "filename": path.name, "content": content,
                      "sha256": hashlib.sha256(content).hexdigest(), "purpose": purpose,
                      "observed_period": period, "kind": kind})
    return items


def existing_identity(previous_root: Path) -> dict:
    path = (previous_root / "finwise.db").resolve(strict=True)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        user = connection.execute("SELECT user_id,password_hash,role,enabled,created_at FROM auth_users WHERE user_id=? AND enabled=1", (USER,)).fetchone()
        if user is None or user["role"] not in {"accountant", "admin"}:
            raise ValueError("未找到原 Staging 操作账号，停止导入")
        grants = connection.execute("SELECT scope_json FROM auth_scope_grants WHERE user_id=?", (USER,)).fetchall()
        if not any(all(json.loads(row[0]).get(k) == v for k, v in SCOPE.model_dump().items()
                       if k not in {"accounting_period_id", "baseline_id"}) for row in grants):
            raise ValueError("原账号未获聚贤达指定账套授权")
        return dict(user)


def run(source_root: Path, previous_root: Path, data_root: Path) -> dict:
    source_root, previous_root, data_root = (p.resolve() for p in (source_root, previous_root, data_root))
    if data_root.exists() or data_root.is_relative_to(source_root) or data_root.is_relative_to(previous_root):
        raise ValueError("新数据目录必须不存在，且不能位于原件或旧账套目录内")
    # Validate all sources and identity before creating anything.
    items, identity = source_manifest(source_root), existing_identity(previous_root)
    data_root.mkdir(mode=0o700, parents=True)
    settings = Settings(root=PROJECT, database_path=data_root / "finwise.db",
                        storage_path=data_root / "artifacts", require_auth=True)
    app = create_app(settings)
    database, service = app.state.database, app.state.service
    with database.connect() as connection:
        connection.execute("INSERT INTO auth_users(user_id,password_hash,role,enabled,created_at) VALUES (?,?,?,?,?)",
                           tuple(identity[k] for k in ("user_id", "password_hash", "role", "enabled", "created_at")))
    # Only the January grant is copied; old sessions and March grants never transfer.
    grant_scope(database, USER, SCOPE)
    service.create_scope(SCOPE, actor_id=ACTOR)
    files = []
    for order, item in enumerate(items, 1):
        artifact = service.create_artifact(ArtifactInput(
            scope=SCOPE, filename=item["filename"], content_base64=base64.b64encode(item["content"]).decode(),
            observed_period=item["observed_period"], source_purpose=item["purpose"],
            source_channel="CONTROLLED_JANUARY_IMPORT", mime_type=mimetypes.guess_type(item["filename"])[0] or "application/octet-stream"), actor_id=ACTOR)
        result = {k: v for k, v in item.items() if k != "content"}
        result.update({"order": order, "artifact_id": artifact["object_id"], "parse_status": "RECEIVED"})
        if item["purpose"] == "historical_reference":
            result["note"] = "2025 全年历史原件已接收；截至 2025-12，不混入一月业务事实，尚未结构化解析或确认基线"
        elif item["observed_period"] != SCOPE.accounting_period_id:
            result["note"] = "1—2 月合并原件，待拆分核对；本轮不提取为一月业务事实"
        elif item["kind"]:
            payload = {"document_kind": item["kind"]}
            effect = service.execute_command(SCOPE, action="parse_artifact", target_id=artifact["object_id"],
                target_version=artifact["version"], idempotency_key="january-parse-" + artifact["object_id"],
                actor_id=ACTOR, role="accountant", payload=payload)["effect"]
            result.update({"parse_status": effect["artifact"]["data"]["parse_status"],
                           "counts": effect["counts"], "errors": effect["errors"]})
        files.append(result)
    overview = service.workbench(SCOPE)
    for item in items:
        if hashlib.sha256(Path(item["source_path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("导入期间来源发生变化，请勿启用新账套，核对导入清单")
    for kind in ("ModelRun", "ProcessingGroup", "ConfirmationCard", "VoucherVersion", "DeliveryPackage"):
        if service.store.list_objects(kind, SCOPE):
            raise RuntimeError("新账套出现了本轮不允许生成的业务结果")
    report = {"created_at": utcnow(), "scope": SCOPE.model_dump(), "database": str(settings.database_path),
              "previous_dataset_unchanged": str(previous_root), "account": USER,
              "files": files, "counts": overview["data_readiness"]["counts"],
              "historical_files": len(HISTORY), "january_files": len(JANUARY) - 1, "mixed_period_files": 1,
              "baseline_status": overview["baseline"]["status"], "model_calls": 0,
              "march_imported": False, "source_hashes_verified": True,
              "note": "仅接收和确定性提取；失败原件保留；未做人工确认、模型分析、凭证或交付"}
    (data_root / "import-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (data_root / "scope.json").write_text(json.dumps(SCOPE.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从 2025 历史账表开始建立全新的一月 Staging，不覆盖旧数据")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--previous-data-root", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    result = run(args.source_root, args.previous_data_root, args.data_root)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, ensure_ascii=False, indent=2))
