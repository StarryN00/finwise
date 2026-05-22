from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Protocol
from urllib import request
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.org_context import get_current_organization_id
from app.models import Enterprise, MonthlyStatement, MonthlyWorkPackage, Report, TaxFilingDraft
from app.reports.health_diagnosis import build_health_diagnosis


class ReportDomainError(Exception):
    pass


class MonthlyPackageNotFoundError(ReportDomainError):
    pass


class HealthReportAiClient(Protocol):
    def generate_report(self, payload: dict) -> dict:
        ...


class MoonshotHealthReportClient:
    def __init__(self, *, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate_report(self, payload: dict) -> dict:
        if not self.api_key:
            raise ReportDomainError("Moonshot API key is not configured.")

        body = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是给代理记账公司使用的企业财务健康诊断分析师。"
                        "只能基于脱敏后的报表指标、税务指标和风险矩阵写报告，不得编造企业名称、税号、地址。"
                        "输出 JSON：{\"sections\":[{\"title\":\"章节标题\",\"content\":[\"段落或要点\"]}]}。"
                        "章节需要贴近企业财务健康诊断报告，包含执行摘要、风险矩阵、偿债、盈利、现金流、税务风险和建议。"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        http_request = request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(http_request, timeout=60) as response:
            response_data = json.loads(response.read().decode("utf-8"))
        content = response_data["choices"][0]["message"]["content"]
        return json.loads(content)


def generate_health_report(
    db: Session,
    *,
    monthly_work_package_id: UUID,
    output_dir: Path | None = None,
    ai_client: HealthReportAiClient | None = None,
) -> Report:
    package = _get_monthly_package(db, monthly_work_package_id)
    enterprise = db.get(Enterprise, package.enterprise_id)
    statement = db.scalar(select(MonthlyStatement).where(MonthlyStatement.monthly_work_package_id == package.id))
    tax_draft = db.scalar(select(TaxFilingDraft).where(TaxFilingDraft.monthly_work_package_id == package.id))
    period = f"{package.period_year}-{package.period_month:02d}"
    should_auto_generate_ai = ai_client is not None or output_dir is None
    enterprise_data = {
        "name": enterprise.name if enterprise else "未命名企业",
        "industry": enterprise.industry if enterprise else "",
        "unified_social_credit_code": enterprise.unified_social_credit_code if enterprise else "",
    }
    statement_data = {
        "estimated_balance_sheet": statement.estimated_balance_sheet if statement else {},
        "estimated_income_statement": statement.estimated_income_statement if statement else {},
    }
    tax_data = tax_draft.data if tax_draft else {}

    diagnosis = build_health_diagnosis(
        enterprise=enterprise_data,
        period=period,
        statement=statement_data,
        tax_draft=tax_data,
    )
    used_ai_report = False
    if diagnosis["status"] == "READY" and should_auto_generate_ai:
        ai_response = _generate_ai_health_report(
            enterprise=enterprise_data,
            period=period,
            statement=statement_data,
            tax_draft=tax_data,
            ai_client=ai_client,
        )
        if ai_response is not None:
            diagnosis["html"] = render_ai_health_report_html(
                enterprise=enterprise_data,
                period=period,
                sections=ai_response.get("sections", []),
            )
            used_ai_report = True

    output_dir = output_dir or get_settings().upload_dir / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"health-report-{package.id}.html"
    html_path.write_text(diagnosis["html"], encoding="utf-8")

    report = db.scalar(
        select(Report).where(
            Report.monthly_work_package_id == package.id,
            Report.report_type == "FINANCIAL_HEALTH",
        )
    )
    if report is None:
        report = Report(
            organization_id=package.organization_id,
            monthly_work_package_id=package.id,
            report_type="FINANCIAL_HEALTH",
        )
        db.add(report)

    report.data_version = {
        "period": period,
        "missing_data": diagnosis["missing_data"],
        "source": "ai_health_report" if used_ai_report else "confirmed_monthly_data",
    }
    report.html_path = str(html_path)
    report.status = diagnosis["status"]
    db.commit()
    db.refresh(report)
    return report


def build_health_report_ai_payload(*, enterprise: dict, period: str, statement: dict, tax_draft: dict) -> dict:
    return {
        "enterprise_profile": {
            "name": "本企业",
            "industry": enterprise.get("industry") or "未填写",
            "taxpayer_type": "一般纳税人",
        },
        "period": period,
        "report_structure": [
            "执行摘要与关键结论",
            "风险等级总览矩阵",
            "公司概况",
            "偿债能力分析",
            "盈利能力分析",
            "运营效率与现金流分析",
            "税务风险与合规提示",
            "风险量化与改进建议",
        ],
        "financial_metrics": {
            "balance_sheet": statement.get("estimated_balance_sheet", {}),
            "income_statement": statement.get("estimated_income_statement", {}),
            "tax_filing": tax_draft,
        },
        "writing_requirements": [
            "用代账公司给企业老板看的中文报告口吻",
            "结论先行，风险分高、中、低",
            "每个风险点尽量给出指标依据和可执行建议",
            "不得输出真实企业名称、税号、地址或联系人",
        ],
    }


def render_ai_health_report_html(*, enterprise: dict, period: str, sections: list[dict]) -> str:
    section_html = []
    for section in sections:
        title = escape(str(section.get("title") or "诊断章节"))
        content_items = section.get("content") or []
        if isinstance(content_items, str):
            content_items = [content_items]
        paragraphs = "".join(f"<p>{escape(str(item))}</p>" for item in content_items if str(item).strip())
        section_html.append(f"<section><h2>{title}</h2>{paragraphs}</section>")
    if not section_html:
        section_html.append("<section><h2>执行摘要与关键结论</h2><p>AI 未返回有效章节，已生成基础诊断框架。</p></section>")

    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{escape(str(enterprise.get("name", "企业")))} {escape(period)} 财务健康诊断</title>
  <style>
    body {{ max-width: 980px; margin: 0 auto; padding: 40px 28px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; color: #172033; line-height: 1.7; background: #f6f8fb; }}
    main {{ padding: 32px; border: 1px solid #d9e2ef; border-radius: 10px; background: #fff; }}
    h1 {{ margin: 0 0 8px; color: #123c7c; font-size: 28px; }}
    h2 {{ margin-top: 30px; padding-bottom: 8px; border-bottom: 1px solid #d9e2ef; color: #1769e0; font-size: 20px; }}
    .subtitle {{ color: #5d6b82; }}
    p {{ margin: 10px 0; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(str(enterprise.get("name", "企业")))} {escape(period)} 财务健康诊断报告</h1>
    <p class="subtitle">基于资产负债表、利润表、申报草稿及已确认账目，由 AI 生成多维度风险分析与建议。</p>
    {''.join(section_html)}
  </main>
</body>
</html>
"""


def desensitize_ai_payload(payload: dict) -> dict:
    sanitized = {}
    sensitive_names = [str(payload.get("enterprise_name", "")), str(payload.get("counterparty_name", ""))]
    for key, value in payload.items():
        if key in {"enterprise_name", "tax_number", "unified_social_credit_code"}:
            continue
        if key == "counterparty_name":
            sanitized[key] = _mask_company_name(str(value))
            continue
        if key == "summary":
            sanitized[key] = _sanitize_summary(str(value), sensitive_names)
            continue
        sanitized[key] = value
    return sanitized


def _generate_ai_health_report(
    *,
    enterprise: dict,
    period: str,
    statement: dict,
    tax_draft: dict,
    ai_client: HealthReportAiClient | None,
) -> dict | None:
    payload = build_health_report_ai_payload(enterprise=enterprise, period=period, statement=statement, tax_draft=tax_draft)
    client = ai_client
    if client is None:
        settings = get_settings()
        if not settings.moonshot_api_key:
            return None
        client = MoonshotHealthReportClient(
            api_key=settings.moonshot_api_key,
            base_url=settings.moonshot_base_url,
            model=settings.moonshot_model,
        )
    try:
        return client.generate_report(payload)
    except Exception:
        return None


def _get_monthly_package(db: Session, monthly_work_package_id: UUID) -> MonthlyWorkPackage:
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None or package.organization_id != get_current_organization_id():
        raise MonthlyPackageNotFoundError("Monthly work package not found.")
    return package


def _mask_company_name(name: str) -> str:
    normalized = name.strip()
    if len(normalized) >= 2:
        return f"{normalized[:2]}***公司"
    return "***公司"


def _sanitize_summary(summary: str, sensitive_names: list[str]) -> str:
    sanitized = summary
    for name in sensitive_names:
        for fragment in _sensitive_name_fragments(name):
            sanitized = sanitized.replace(fragment, "交易对手")
    sanitized = re.sub(r"9[0-9A-Z]{10,}", "税号", sanitized)
    return sanitized


def _sensitive_name_fragments(name: str) -> list[str]:
    normalized = name.strip()
    if not normalized:
        return []
    fragments = [normalized]
    for suffix in ("有限责任公司", "股份有限公司", "有限公司", "公司"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            fragments.append(normalized[: -len(suffix)])
            break
    return fragments
