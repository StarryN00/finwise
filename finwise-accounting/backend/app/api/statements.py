from __future__ import annotations

from html import escape
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import Enterprise, MonthlyStatement, MonthlyWorkPackage
from app.schemas.statement import MonthlyStatementRead
from app.services.statement_service import MonthlyPackageNotFoundError, generate_monthly_statement


router = APIRouter(tags=["statements"])

STATEMENT_FIELD_LABELS = {
    "bank_credit_total": "银行收入合计",
    "bank_debit_total": "银行支出合计",
    "cash_net_movement": "现金净流入",
    "vat_payable_estimate": "应纳增值税估算",
    "revenue": "营业收入",
    "output_tax": "销项税额",
    "cost": "营业成本",
    "input_tax": "进项税额",
    "expense": "期间费用",
    "gross_profit": "毛利",
    "operating_profit": "营业利润",
    "balance_sheet": "资产负债表差异",
    "income_statement": "利润表差异",
}


@router.post("/api/monthly-packages/{package_id}/statements/generate", response_model=MonthlyStatementRead)
def generate_statement_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return generate_monthly_statement(db, monthly_work_package_id=package_id)
    except MonthlyPackageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/monthly-packages/{package_id}/statements/latest", response_model=MonthlyStatementRead)
def latest_statement_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    statement = _latest_statement(db, package_id)
    if statement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monthly statement not found.")
    return statement


@router.get("/api/monthly-packages/{package_id}/statements/latest/html", response_class=HTMLResponse)
def latest_statement_html_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    package = db.get(MonthlyWorkPackage, package_id)
    statement = _latest_statement(db, package_id)
    if package is None or statement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monthly statement not found.")
    enterprise = db.get(Enterprise, package.enterprise_id)
    return HTMLResponse(_render_statement_html(statement, enterprise=enterprise, package=package))


def _latest_statement(db: Session, package_id: UUID) -> MonthlyStatement | None:
    return db.scalar(
        select(MonthlyStatement)
        .where(MonthlyStatement.monthly_work_package_id == package_id)
        .order_by(MonthlyStatement.created_at.desc(), MonthlyStatement.id.desc())
    )


def _render_statement_html(
    statement: MonthlyStatement,
    *,
    enterprise: Enterprise | None,
    package: MonthlyWorkPackage,
) -> str:
    enterprise_name = enterprise.name if enterprise else "未知企业"
    period = f"{package.period_year}-{package.period_month:02d}"
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{escape(enterprise_name)} {period} 每月账目与报表</title>
  <style>
    body {{ margin: 0; padding: 32px; color: #172033; background: #f5f7fb; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ max-width: 980px; margin: 0 auto; }}
    header, section {{ margin-bottom: 18px; padding: 22px; border: 1px solid #dbe3ef; border-radius: 8px; background: #fff; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    h2 {{ margin: 0 0 14px; font-size: 18px; }}
    p {{ margin: 0; color: #667085; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #edf1f7; text-align: left; }}
    th {{ color: #667085; font-weight: 600; background: #f8fafc; }}
    td:last-child {{ text-align: right; font-variant-numeric: tabular-nums; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{escape(enterprise_name)} {period} 每月账目与报表</h1>
      <p>基于已确认流水、发票和账目分类生成的在线预览。</p>
    </header>
    <section>
      <h2>资产负债表估算</h2>
      {_render_dict_table(statement.estimated_balance_sheet)}
    </section>
    <section>
      <h2>利润表估算</h2>
      {_render_dict_table(statement.estimated_income_statement)}
    </section>
    <section>
      <h2>差异与提醒</h2>
      {_render_dict_table(statement.difference_summary)}
    </section>
  </main>
</body>
</html>
"""


def _render_dict_table(data: dict) -> str:
    if not data:
        return "<p>暂无数据</p>"
    rows = "\n".join(
        f"<tr><td>{escape(_statement_label(str(key)))}</td><td>{_render_statement_value(value)}</td></tr>"
        for key, value in data.items()
    )
    return f"<table><thead><tr><th>项目</th><th>金额/说明</th></tr></thead><tbody>{rows}</tbody></table>"


def _statement_label(key: str) -> str:
    return STATEMENT_FIELD_LABELS.get(key, key)


def _render_statement_value(value) -> str:
    if isinstance(value, dict):
        return escape("；".join(f"{_statement_label(str(key))}: {item}" for key, item in value.items()))
    return escape(str(value))
