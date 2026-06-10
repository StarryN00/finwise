# Report Generation Router
# 报告生成 API 路由

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
from datetime import datetime, date
from decimal import Decimal
import json

from backend.reports.generator import (
    ReportGenerator,
    ReportType,
    ReportFormat,
    ReportGenerationRequest,
    generate_vat_report,
    generate_health_report,
    generate_financing_score_report
)
from backend.storage.manager import (
    enterprise_store,
    invoice_store,
    bank_transaction_store,
    vat_filing_store,
    health_report_store,
)
from backend.services.health_report_template import (
    build_data_completeness,
    build_financial_health_report,
    save_financial_health_report,
)
from backend.routers.auth import get_current_user


router = APIRouter(prefix="/api/reports", tags=["报告生成"])


# ============ Request/Response Models ============

class VATReportRequest(BaseModel):
    """增值税申报报告请求"""
    enterprise_id: str
    period_year: int
    period_month: int


class HealthReportRequest(BaseModel):
    """财务健康分析报告请求"""
    enterprise_id: str
    report_type: str = "FULL"  # FULL | QUICK
    period_year: Optional[int] = None
    period_month: Optional[int] = None


class FinancingScoreReportRequest(BaseModel):
    """融资评分报告请求"""
    enterprise_id: str


class ReportGenerationRequestDTO(BaseModel):
    """通用报告生成请求"""
    report_type: str  # "VAT_FILING" | "HEALTH_ANALYSIS" | "FINANCING_SCORE"
    enterprise_id: str
    format: str = "JSON"  # "JSON" | "HTML" | "PDF" | "EXCEL"
    period_year: Optional[int] = None
    period_month: Optional[int] = None
    options: Optional[dict] = None


class MonthlyReportRequest(BaseModel):
    enterprise_id: str
    period_year: int
    period_month: int


# ============ API Routes ============


def _to_decimal(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _month_prefix(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _grade(score: int) -> str:
    if score >= 90:
        return "A_PLUS"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B_PLUS"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def _build_monthly_report(enterprise_id: str, period_year: int, period_month: int) -> dict:
    enterprise = enterprise_store.get_by_id(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    prefix = _month_prefix(period_year, period_month)
    invoices = [
        inv for inv in invoice_store.filter(enterprise_id=enterprise_id)
        if str(inv.get("issue_date", "")).startswith(prefix)
    ]
    transactions = [
        tx for tx in bank_transaction_store.filter(enterprise_id=enterprise_id)
        if str(tx.get("transaction_date", "")).startswith(prefix)
        and tx.get("status") != "DELETED"
    ]

    valid_invoices = [inv for inv in invoices if inv.get("invoice_status") != "VOID"]
    output_invoices = [
        inv for inv in valid_invoices
        if (inv.get("direction") or inv.get("invoice_type")) in {"SALES", "OUTPUT"}
    ]
    input_invoices = [
        inv for inv in valid_invoices
        if (inv.get("direction") or inv.get("invoice_type")) in {"PURCHASE", "INPUT"}
    ]
    sales_amount = sum((_to_decimal(inv.get("amount")) for inv in output_invoices), Decimal("0"))
    purchase_amount = sum((_to_decimal(inv.get("amount")) for inv in input_invoices), Decimal("0"))
    output_tax = sum((_to_decimal(inv.get("tax_amount")) for inv in output_invoices), Decimal("0"))
    input_tax = sum((_to_decimal(inv.get("tax_amount")) for inv in input_invoices), Decimal("0"))

    cash_inflow = sum((_to_decimal(tx.get("credit_amount")) for tx in transactions), Decimal("0"))
    cash_outflow = sum((_to_decimal(tx.get("debit_amount")) for tx in transactions), Decimal("0"))
    net_cash_flow = cash_inflow - cash_outflow
    ending_balances = [
        _to_decimal(tx.get("balance"))
        for tx in sorted(transactions, key=lambda item: item.get("transaction_date", ""))
        if tx.get("balance") is not None
    ]
    ending_balance = ending_balances[-1] if ending_balances else Decimal("0")

    vat_payable = max(output_tax - input_tax, Decimal("0"))
    surcharge = (vat_payable * Decimal("0.12")).quantize(Decimal("0.01"))
    total_tax = vat_payable + surcharge

    cash_flow_score = 85 if net_cash_flow > 0 else 55 if cash_inflow else 40
    revenue_score = min(95, 55 + int(sales_amount / Decimal("10000"))) if sales_amount else 45
    tax_score = 75 if vat_payable >= 0 else 60
    operation_score = min(95, 50 + len(transactions))
    financing_score = round((cash_flow_score * 0.35) + (revenue_score * 0.3) + (operation_score * 0.2) + (tax_score * 0.15))
    overall_score = round((cash_flow_score + revenue_score + operation_score + tax_score) / 4)

    report_id = f"MR-{period_year}{period_month:02d}-{enterprise_id}"
    report = {
        "id": report_id,
        "report_id": report_id,
        "report_type": "MONTHLY_FINANCIAL",
        "enterprise_id": enterprise_id,
        "enterprise_name": enterprise.get("name"),
        "period_year": period_year,
        "period_month": period_month,
        "analysis_date": date.today().isoformat(),
        "invoice_count": len(invoices),
        "transaction_count": len(transactions),
        "sales_amount": float(sales_amount),
        "purchase_amount": float(purchase_amount),
        "output_tax": float(output_tax),
        "input_tax": float(input_tax),
        "vat_payable": float(vat_payable),
        "surcharge_amount": float(surcharge),
        "total_tax": float(total_tax),
        "cash_inflow": float(cash_inflow),
        "cash_outflow": float(cash_outflow),
        "net_cash_flow": float(net_cash_flow),
        "ending_balance": float(ending_balance),
        "overall_score": overall_score,
        "overall_grade": _grade(overall_score),
        "financing_score": financing_score,
        "dimensions": {
            "cash_flow": cash_flow_score,
            "revenue": revenue_score,
            "operation": operation_score,
            "tax_compliance": tax_score,
        },
        "risk_alerts": [
            alert for alert in [
                "本月经营现金流为负，需关注回款与支出节奏" if net_cash_flow < 0 else "",
                "本月无发票数据，税务与收入分析可信度较低" if not invoices else "",
                "本月无银行流水，现金流分析可信度较低" if not transactions else "",
            ] if alert
        ],
        "suggestions": [
            "优先核对流水与发票匹配情况",
            "按月沉淀销项、进项和现金流趋势，用于后续融资评分",
        ],
        "status": "COMPLETED",
        "created_at": datetime.utcnow().isoformat(),
    }
    return report


@router.post("/monthly/generate")
async def generate_monthly_report(
    request: MonthlyReportRequest,
    current_user: dict = Depends(get_current_user),
):
    report = _build_monthly_report(request.enterprise_id, request.period_year, request.period_month)
    existing = health_report_store.first(
        enterprise_id=request.enterprise_id,
        report_type="MONTHLY_FINANCIAL",
        period_year=request.period_year,
        period_month=request.period_month,
    )
    if existing:
        health_report_store.update(existing["id"], **report)
    else:
        health_report_store.create(**report)
    return {"report_id": report["report_id"], "status": "COMPLETED", "data": report}


@router.get("/monthly/{enterprise_id}")
async def get_monthly_reports(
    enterprise_id: str,
    period_year: Optional[int] = Query(None),
    period_month: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    reports = health_report_store.filter(enterprise_id=enterprise_id, report_type="MONTHLY_FINANCIAL")
    if period_year is not None:
        reports = [r for r in reports if r.get("period_year") == period_year]
    if period_month is not None:
        reports = [r for r in reports if r.get("period_month") == period_month]
    reports.sort(key=lambda item: (item.get("period_year", 0), item.get("period_month", 0)), reverse=True)
    return {"items": reports, "total": len(reports)}


@router.get("/data-completeness/{enterprise_id}")
async def get_report_data_completeness(
    enterprise_id: str,
    period_year: int = Query(..., ge=2000, le=2100),
    period_month: int = Query(..., ge=1, le=12),
    current_user: dict = Depends(get_current_user),
):
    enterprise = enterprise_store.get_by_id(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    return build_data_completeness(enterprise_id, period_year, period_month)

@router.post("/vat/generate")
async def generate_vat_report_handler(
    request: VATReportRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    生成增值税申报报告

    - **enterprise_id**: 企业ID
    - **period_year**: 申报年份
    - **period_month**: 申报月份
    """
    try:
        report_data = generate_vat_report(
            enterprise_id=request.enterprise_id,
            period_year=request.period_year,
            period_month=request.period_month
        )

        return {
            "report_id": report_data["report_id"],
            "report_type": "VAT_FILING",
            "status": "COMPLETED",
            "data": report_data,
            "download_url": f"/api/reports/{report_data['report_id']}/export"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vat/{enterprise_id}")
async def get_vat_report_list(
    enterprise_id: str,
    period_year: Optional[int] = Query(None),
    period_month: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """
    获取企业增值税申报报告列表

    - **enterprise_id**: 企业ID
    - **period_year**: 申报年份（可选）
    - **period_month**: 申报月份（可选）
    """
    # Filter from vat_filing_store
    filters = {"enterprise_id": enterprise_id, "report_type": "VAT_FILING"}
    reports = vat_filing_store.filter(**filters)

    # Apply period filters
    if period_year is not None:
        reports = [r for r in reports if r.get('period_year') == period_year]
    if period_month is not None:
        reports = [r for r in reports if r.get('period_month') == period_month]

    # Build response items
    items = []
    for r in reports:
        items.append({
            "report_id": r.get('filing_id') or r.get('report_id') or r.get('id'),
            "enterprise_id": r.get('enterprise_id'),
            "period_year": r.get('period_year'),
            "period_month": r.get('period_month'),
            "sales_amount_excl_tax": r.get('sales_amount_excl_tax', '0'),
            "tax_amount": r.get('tax_amount', '0'),
            "total_tax_and_surcharge": r.get('total_tax_and_surcharge', '0'),
            "status": r.get('status', 'DRAFT'),
            "created_at": r.get('created_at', '')
        })

    return {"items": items, "total": len(items)}


@router.post("/health/generate")
async def generate_health_report_handler(
    request: HealthReportRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    生成财务健康分析报告

    - **enterprise_id**: 企业ID
    - **report_type**: 报告类型 (FULL | QUICK)
    """
    try:
        today = date.today()
        period_year = request.period_year or today.year
        period_month = request.period_month or today.month
        report_data = build_financial_health_report(
            request.enterprise_id,
            period_year,
            period_month,
        )
        saved = save_financial_health_report(report_data)

        return {
            "report_id": saved["report_id"],
            "report_number": saved["report_number"],
            "report_type": "HEALTH_ANALYSIS",
            "status": "COMPLETED",
            "data": saved,
            "download_url": f"/api/reports/{saved['report_id']}/export"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/{enterprise_id}")
async def get_health_report_list(
    enterprise_id: str,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """
    获取企业财务健康分析报告列表

    - **enterprise_id**: 企业ID
    - **limit**: 返回数量
    - **offset**: 偏移量
    """
    # Filter from health_report_store for HEALTH_ANALYSIS type
    filters = {"enterprise_id": enterprise_id, "report_type": "HEALTH_ANALYSIS"}
    all_reports = health_report_store.filter(**filters)

    # Sort by created_at desc (default in filter)
    total = len(all_reports)

    # Apply pagination
    reports = all_reports[offset:offset+limit]

    items = []
    for r in reports:
        # Try to parse data JSON
        data_raw = r.get('data', '{}')
        try:
            data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
        except (json.JSONDecodeError, TypeError):
            data = {}

        items.append({
            "report_id": r.get('report_id') or r.get('id'),
            "report_number": r.get('report_number', ''),
            "enterprise_id": r.get('enterprise_id'),
            "enterprise_name": r.get('enterprise_name', ''),
            "analysis_date": data.get('analysis_date', r.get('created_at', '')[:10]),
            "overall_score": r.get('overall_score') or data.get('overall_score', 0),
            "overall_grade": r.get('overall_grade') or data.get('overall_grade', ''),
            "status": r.get('status', 'COMPLETED'),
            "created_at": r.get('created_at', '')
        })

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/health/{enterprise_id}/latest")
async def get_latest_health_report(
    enterprise_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    获取企业最新财务健康分析报告

    - **enterprise_id**: 企业ID
    """
    # Get latest health report from store
    reports = health_report_store.filter(
        enterprise_id=enterprise_id,
        report_type="HEALTH_ANALYSIS",
    )

    if not reports:
        raise HTTPException(status_code=404, detail="No health report found for this enterprise")

    # Sort by created_at desc and take first
    latest = reports[0]

    # Parse data JSON
    data_raw = latest.get('data', '{}')
    try:
        data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
    except (json.JSONDecodeError, TypeError):
        data = {}

    return {
        "report_id": latest.get('report_id') or latest.get('id'),
        "report_number": latest.get('report_number', data.get('report_number', '')),
        "enterprise_id": latest.get('enterprise_id'),
        "enterprise_name": latest.get('enterprise_name', data.get('enterprise_name', '')),
        "analysis_date": data.get('analysis_date', latest.get('created_at', '')[:10]),
        "overall_score": latest.get('overall_score') or data.get('overall_score', 0),
        "overall_grade": latest.get('overall_grade') or data.get('overall_grade', ''),
        "five_dimension_scores": data.get('five_dimension_scores', {}),
        "radar_data": data.get('radar_data', {}),
        "key_metrics": data.get('key_metrics', {}),
        "ai_interpretation": data.get('ai_interpretation', ''),
        "risk_alerts": data.get('risk_alerts', []),
        "improvement_suggestions": data.get('improvement_suggestions', []),
        "financing_score": latest.get('financing_score') or data.get('financing_score', 0),
        "estimated_loan_amount": data.get('estimated_loan_amount', 0),
        "matched_products": data.get('matched_products', []),
        "status": latest.get('status', 'COMPLETED')
    }


@router.post("/financing/generate")
async def generate_financing_score_report_handler(
    request: FinancingScoreReportRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    生成融资评分报告

    - **enterprise_id**: 企业ID
    """
    try:
        report_data = generate_financing_score_report(
            enterprise_id=request.enterprise_id
        )

        return {
            "score_id": report_data["score_id"],
            "report_type": "FINANCING_SCORE",
            "status": "COMPLETED",
            "data": report_data,
            "download_url": f"/api/reports/{report_data['score_id']}/export"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/financing/{enterprise_id}")
async def get_financing_score_history(
    enterprise_id: str,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """
    获取企业融资评分历史

    - **enterprise_id**: 企业ID
    - **limit**: 返回数量
    - **offset**: 偏移量
    """
    # Filter from health_report_store for FINANCING_SCORE type
    filters = {"enterprise_id": enterprise_id, "report_type": "FINANCING_SCORE"}
    all_scores = health_report_store.filter(**filters)

    total = len(all_scores)
    scores = all_scores[offset:offset+limit]

    items = []
    for s in scores:
        # Try to parse data JSON
        data_raw = s.get('data', '{}')
        try:
            data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
        except (json.JSONDecodeError, TypeError):
            data = {}

        items.append({
            "score_id": s.get('report_id') or s.get('id'),
            "enterprise_id": s.get('enterprise_id'),
            "enterprise_name": s.get('enterprise_name', ''),
            "score_date": data.get('score_date', s.get('created_at', '')[:10]),
            "score": s.get('score') or data.get('score', 0),
            "level": s.get('level') or data.get('level', ''),
            "estimated_loan_amount": s.get('estimated_loan_amount') or data.get('estimated_loan_amount', 0),
            "status": s.get('status', 'COMPLETED'),
            "created_at": s.get('created_at', '')
        })

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.post("/generate")
async def generate_report_handler(
    request: ReportGenerationRequestDTO,
    current_user: dict = Depends(get_current_user),
):
    """
    通用报告生成接口

    - **report_type**: 报告类型 (VAT_FILING | HEALTH_ANALYSIS | FINANCING_SCORE)
    - **enterprise_id**: 企业ID
    - **format**: 导出格式 (JSON | HTML | PDF | EXCEL)
    - **period_year/month**: 申报期间（VAT报告需要）
    - **options**: 其他选项
    """
    try:
        report_format = ReportFormat(request.format)
        report_type = ReportType(request.report_type)

        gen_request = ReportGenerationRequest(
            report_type=report_type,
            enterprise_id=request.enterprise_id,
            format=report_format,
            period_year=request.period_year,
            period_month=request.period_month,
            options=request.options
        )

        generator = ReportGenerator()
        result = generator.generate_report(gen_request)

        return {
            "report_id": result.get("report_id") or result.get("score_id"),
            "report_type": request.report_type,
            "status": "COMPLETED",
            "data": result,
            "export_url": f"/api/reports/{result.get('report_id', result.get('score_id'))}/export?format={request.format}"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{report_id}/export")
async def export_report(
    report_id: str,
    format: str = Query("JSON", pattern="^(JSON|HTML|PDF|EXCEL)$"),
    current_user: dict = Depends(get_current_user),
):
    """
    导出报告为指定格式

    - **report_id**: 报告ID
    - **format**: 导出格式 (JSON | HTML | PDF | EXCEL)
    """
    generator = ReportGenerator()

    try:
        if format == "HTML":
            html_content = generator.export_to_format(report_id, ReportFormat.HTML)
            return {
                "content_type": "text/html",
                "content": html_content
            }
        else:
            # JSON/PDF/EXCEL 返回下载链接
            return {
                "download_url": f"/api/files/reports/{report_id}.{format.lower()}",
                "expires_at": "2026-05-10T00:00:00Z"
            }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
