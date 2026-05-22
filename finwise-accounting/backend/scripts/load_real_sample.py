from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
from sqlalchemy import delete

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import initialize_database  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AccountingLine,
    AuditLog,
    BankTransaction,
    Enterprise,
    ImportBatch,
    InitialFinancialSnapshot,
    Invoice,
    MatchRecord,
    MatchingRule,
    MonthlyStatement,
    MonthlyWorkPackage,
    Report,
    TaxFilingDraft,
)
from app.services.enterprise_service import create_enterprise, create_monthly_work_package, save_initial_snapshot  # noqa: E402
from app.services.import_service import import_bank_rows, import_invoice_rows  # noqa: E402
from app.services.matching_service import run_matching  # noqa: E402
from app.services.report_service import generate_health_report  # noqa: E402
from app.services.statement_service import generate_monthly_statement  # noqa: E402
from app.services.tax_service import generate_tax_filing_draft  # noqa: E402


REAL_DATA_DIR = Path("/Volumes/共享文件夹/财务项目/银行流水/昆山晟立烁科技有限公司")
ENTERPRISE_NAME = "昆山晟立烁科技有限公司"
TAX_NUMBER = "91320583MAE5AA949G"


def main() -> None:
    if not REAL_DATA_DIR.exists():
        raise SystemExit(f"Real data directory not found: {REAL_DATA_DIR}")

    initialize_database()
    with SessionLocal() as db:
        _clear_sample_data(db)
        enterprise = create_enterprise(
            db,
            name=ENTERPRISE_NAME,
            unified_social_credit_code=TAX_NUMBER,
            taxpayer_type="GENERAL",
            industry="智能设备/机器人",
            city="昆山市",
        )
        save_initial_snapshot(
            db,
            enterprise_id=enterprise.id,
            balance_sheet_data=_read_balance_sheet(),
            income_statement_data=_read_income_statement(),
        )
        package = create_monthly_work_package(db, enterprise_id=enterprise.id, year=2026, month=3)
        bank_result = import_bank_rows(
            db,
            monthly_work_package_id=package.id,
            rows=_read_bank_rows("昆山晟立烁科技有限公司3月银行流水.xls"),
        )
        input_result = import_invoice_rows(
            db,
            monthly_work_package_id=package.id,
            direction="INPUT",
            rows=_read_invoice_rows("昆山晟立烁科技有限公司3月进项.xlsx"),
        )
        output_result = import_invoice_rows(
            db,
            monthly_work_package_id=package.id,
            direction="OUTPUT",
            rows=_read_invoice_rows("昆山晟立烁科技有限公司3月销项.xlsx"),
        )
        matching_result = run_matching(db, monthly_work_package_id=package.id)
        statement = generate_monthly_statement(db, monthly_work_package_id=package.id)
        tax_draft = generate_tax_filing_draft(db, monthly_work_package_id=package.id)
        report = generate_health_report(db, monthly_work_package_id=package.id)
        summary = {
            "enterprise": ENTERPRISE_NAME,
            "bank_rows": bank_result["created"],
            "input_invoices": input_result["created"],
            "output_invoices": output_result["created"],
            "exact_matches": matching_result["exact_matches"],
            "pending_confirmations": matching_result["pending_confirmations"],
            "revenue": statement.estimated_income_statement.get("revenue"),
            "vat_payable": tax_draft.data.get("vat_payable"),
            "report_status": report.status,
        }
    print(summary)


def _clear_sample_data(db) -> None:
    package_ids = [
        package.id
        for package in db.query(MonthlyWorkPackage)
        .join(Enterprise, Enterprise.id == MonthlyWorkPackage.enterprise_id)
        .filter(Enterprise.unified_social_credit_code == TAX_NUMBER)
    ]
    if package_ids:
        for model in (AuditLog, Report, TaxFilingDraft, MonthlyStatement, AccountingLine, MatchRecord, Invoice, BankTransaction, ImportBatch):
            db.execute(delete(model).where(model.monthly_work_package_id.in_(package_ids)))
        db.execute(delete(MonthlyWorkPackage).where(MonthlyWorkPackage.id.in_(package_ids)))
    enterprise = db.query(Enterprise).filter(Enterprise.unified_social_credit_code == TAX_NUMBER).one_or_none()
    if enterprise is not None:
        db.execute(delete(MatchingRule).where(MatchingRule.enterprise_id == enterprise.id))
        db.execute(delete(InitialFinancialSnapshot).where(InitialFinancialSnapshot.enterprise_id == enterprise.id))
        db.delete(enterprise)
    db.commit()


def _read_bank_rows(filename: str) -> list[dict]:
    frame = pd.read_excel(REAL_DATA_DIR / filename, header=4)
    frame = frame.dropna(how="all")
    return frame.to_dict(orient="records")


def _read_invoice_rows(filename: str) -> list[dict]:
    frame = pd.read_excel(REAL_DATA_DIR / filename, sheet_name="发票基础信息")
    frame = frame[frame["序号"].astype(str) != "合计行"]
    frame = frame.dropna(how="all")
    return frame.to_dict(orient="records")


def _read_balance_sheet() -> dict:
    frame = pd.read_excel(REAL_DATA_DIR / "昆山晟立烁科技有限公司_资产负债表_202603 (1).xls", header=None)
    return {
        "资产总计": _cell(frame, 35, 2),
        "负债合计": _cell(frame, 26, 6),
        "所有者权益合计": _cell(frame, 34, 6),
        "货币资金": _cell(frame, 5, 2),
        "应收账款": _cell(frame, 8, 2),
        "存货": _cell(frame, 13, 2),
        "应付账款": _cell(frame, 7, 6),
    }


def _read_income_statement() -> dict:
    frame = pd.read_excel(REAL_DATA_DIR / "昆山晟立烁科技有限公司_利润表_202603.xls", header=None)
    return {
        "营业收入": _cell(frame, 4, 2),
        "营业成本": _cell(frame, 5, 2),
        "管理费用": _cell(frame, 17, 2),
        "营业利润": _cell(frame, 24, 2),
        "净利润": _cell(frame, 35, 2),
    }


def _cell(frame: pd.DataFrame, row: int, column: int) -> str:
    value = frame.iat[row, column]
    if pd.isna(value):
        return "0"
    return str(value)


if __name__ == "__main__":
    main()
