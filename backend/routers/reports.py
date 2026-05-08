# Report Generation Router
# 报告生成 API 路由

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
from datetime import datetime, date
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
    vat_filing_store,
    health_report_store,
)


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


# ============ API Routes ============

@router.post("/vat/generate")
async def generate_vat_report_handler(request: VATReportRequest):
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
    period_month: Optional[int] = Query(None)
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
async def generate_health_report_handler(request: HealthReportRequest):
    """
    生成财务健康分析报告

    - **enterprise_id**: 企业ID
    - **report_type**: 报告类型 (FULL | QUICK)
    """
    try:
        report_data = generate_health_report(
            enterprise_id=request.enterprise_id,
            report_type=request.report_type
        )

        return {
            "report_id": report_data["report_id"],
            "report_number": report_data["report_number"],
            "report_type": "HEALTH_ANALYSIS",
            "status": "COMPLETED",
            "data": report_data,
            "download_url": f"/api/reports/{report_data['report_id']}/export"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/{enterprise_id}")
async def get_health_report_list(
    enterprise_id: str,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0)
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
async def get_latest_health_report(enterprise_id: str):
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
async def generate_financing_score_report_handler(request: FinancingScoreReportRequest):
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
    offset: int = Query(0, ge=0)
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
async def generate_report_handler(request: ReportGenerationRequestDTO):
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
    format: str = Query("JSON", pattern="^(JSON|HTML|PDF|EXCEL)$")
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