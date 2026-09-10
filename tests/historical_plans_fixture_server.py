"""Disposable authenticated fixtures for issue handling; no retained data access."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import create_user, grant_scope
from app.config import Settings
from app.main import create_app
from app.ontology.contracts import Scope
from app.historical import read_workbook
from test_historical_preparation import unmapped_workbooks, upload, workbooks
from test_tabular_ingestion import xlsx_fixture


def build(root):
    if (root / "issue-plans-test.db").exists():
        raise RuntimeError("Refusing to reuse an existing database")
    app = create_app(Settings(root=Path(__file__).resolve().parents[1], database_path=root / "issue-plans-test.db",
                              storage_path=root / "artifacts", require_auth=True))
    users = {"plan-author": "accountant", "plan-reviewer": "reviewer", "plan-viewer": "viewer"}
    for user, role in users.items():
        create_user(app.state.database, user, "IssuePlanTest!2026", role)
    balance, journal = unmapped_workbooks()
    rows = [r["values"] for r in read_workbook(journal)[0]["rows"]]
    rows[-1:-1] = [["2025-12-31", "记-003", "待核对调整", "另一个待核对科目", "8888", "待核对科目", None, None, 20, 0],
                   ["2025-12-31", "记-003", "待核对调整", "另一个待核对科目", "8888", "待核对科目", None, None, -20, 0]]
    journal = xlsx_fixture([("序时账", rows)])
    for name in ("方案核对甲", "方案核对乙", "未授权企业"):
        scope = Scope(tenant_id="issue-plan-test", organization_id="fixture", legal_entity_id=name,
                      ledger_id="test-ledger", accounting_period_id="2026-01", baseline_id="baseline-2026-01")
        app.state.service.create_scope(scope)
        if name != "未授权企业":
            for user in users:
                grant_scope(app.state.database, user, scope)
        for filename, content in zip(("余额.xlsx", "序时.xlsx"), (balance, journal)):
            upload(app.state.service, scope, content, filename)
        app.state.service.historical.run_once()
    # Corrected source pair is used only in the explicit upload regression.
    for filename, content in zip(("corrected-balance.xlsx", "corrected-journal.xlsx"), workbooks()):
        (root / filename).write_bytes(content)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(build(args.root), host="127.0.0.1", port=args.port)
