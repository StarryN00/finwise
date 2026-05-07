# Report Generation Router
# 报告生成 API 路由

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
from datetime import date

from backend.reports.generator import (
    ReportGenerator,
    ReportType,
    ReportFormat,
    ReportGenerationRequest,
    generate_vat_report,
    generate_health_report,
    generate_financing_score_report
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
    # 模拟数据
    mock_reports = [
        {
            "report_id": "vat-rpt-001",
            "enterprise_id": enterprise_id,
            "period_year": 2026,
            "period_month": 3,
            "total_tax_and_surcharge": "179752.95",
            "status": "CONFIRMED",
            "created_at": "2026-04-05T10:30:00Z"
        },
        {
            "report_id": "vat-rpt-002",
            "enterprise_id": enterprise_id,
            "period_year": 2026,
            "period_month": 4,
            "total_tax_and_surcharge": "212108.48",
            "status": "DRAFT",
            "created_at": "2026-05-07T14:22:00Z"
        }
    ]

    if period_year:
        mock_reports = [r for r in mock_reports if r["period_year"] == period_year]
    if period_month:
        mock_reports = [r for r in mock_reports if r["period_month"] == period_month]

    return {"items": mock_reports, "total": len(mock_reports)}


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
    # 模拟数据
    mock_reports = [
        {
            "report_id": "health-rpt-001",
            "report_number": "HR-2026-ABC12345",
            "enterprise_id": enterprise_id,
            "analysis_date": "2026-04-15",
            "overall_score": 78,
            "overall_grade": "B_PLUS",
            "status": "COMPLETED",
            "created_at": "2026-04-15T16:30:00Z"
        },
        {
            "report_id": "health-rpt-002",
            "report_number": "HR-2026-DEF67890",
            "enterprise_id": enterprise_id,
            "analysis_date": "2026-05-01",
            "overall_score": 82,
            "overall_grade": "B_PLUS",
            "status": "COMPLETED",
            "created_at": "2026-05-01T09:15:00Z"
        }
    ]

    return {
        "items": mock_reports[offset:offset+limit],
        "total": len(mock_reports),
        "limit": limit,
        "offset": offset
    }


@router.get("/health/{enterprise_id}/latest")
async def get_latest_health_report(enterprise_id: str):
    """
    获取企业最新财务健康分析报告

    - **enterprise_id**: 企业ID
    """
    # 模拟最新报告数据
    latest_report = {
        "report_id": "health-rpt-002",
        "report_number": "HR-2026-DEF67890",
        "enterprise_id": enterprise_id,
        "enterprise_name": "昆山某某科技有限公司",
        "analysis_date": "2026-05-01",
        "overall_score": 82,
        "overall_grade": "B_PLUS",
        "five_dimension_scores": {
            "profitability": {"score": 82.5, "description": "盈利能力良好"},
            "solvency": {"score": 75.0, "description": "偿债能力中等"},
            "operation_efficiency": {"score": 80.0, "description": "运营效率较高"},
            "growth": {"score": 72.5, "description": "增长潜力一般"},
            "cash_flow": {"score": 85.0, "description": "现金流状况优秀"}
        },
        "key_metrics": {
            "gross_margin": "28.5%",
            "net_margin": "12.3%",
            "roa": "8.7%"
        },
        "ai_interpretation": "该公司整体财务状况良好...",
        "financing_score": 82,
        "estimated_loan_amount": 5_000_000,
        "status": "COMPLETED"
    }

    return latest_report


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
    # 模拟数据
    mock_scores = [
        {
            "score_id": "fin-sco-001",
            "enterprise_id": enterprise_id,
            "score_date": "2026-04-10",
            "score": 78,
            "level": "MEDIUM",
            "estimated_loan_amount": "3,500,000",
            "status": "COMPLETED"
        },
        {
            "score_id": "fin-sco-002",
            "enterprise_id": enterprise_id,
            "score_date": "2026-05-07",
            "score": 82,
            "level": "HIGH",
            "estimated_loan_amount": "5,000,000",
            "status": "COMPLETED"
        }
    ]

    return {
        "items": mock_scores[offset:offset+limit],
        "total": len(mock_scores),
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