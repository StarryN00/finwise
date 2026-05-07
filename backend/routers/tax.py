# Tax Calculation Router
# 税务计算 API 路由

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
from decimal import Decimal
from datetime import date

from backend.tax.calculator import (
    TaxCalculationInput,
    TaxpayerType,
    Province,
    calculate_vat,
    calculate_cit,
    calculate_full_tax,
    VATCalculationResult,
    CITCalculationResult,
    TaxCalculationResult
)


router = APIRouter(prefix="/api/tax", tags=["税务计算"])


# ============ Request Models ============

class VATCalculateRequest(BaseModel):
    """增值税计算请求"""
    enterprise_id: str
    period_year: int
    period_month: int
    taxpayer_type: str  # "GENERAL" | "SMALL"
    sales_amount: Decimal
    tax_amount: Decimal
    tax_amount_is_tax_included: bool = True
    province: str = "JIANGSU"


class CITCalculateRequest(BaseModel):
    """企业所得税计算请求"""
    enterprise_id: str
    period_year: int
    period_month: int
    taxable_income: Decimal
    is_high_tech: bool = False
    is_small_low_profit: bool = False


class FullTaxCalculateRequest(BaseModel):
    """完整税务计算请求（增值税 + 附加税 + 企业所得税）"""
    enterprise_id: str
    period_year: int
    period_month: int
    taxpayer_type: str
    sales_amount: Decimal
    tax_amount: Decimal
    tax_amount_is_tax_included: bool = True
    taxable_income: Optional[Decimal] = None
    is_high_tech: bool = False
    is_small_low_profit: bool = False


# ============ Response Models ============

class VATCalculateResponse(BaseModel):
    """增值税计算响应"""
    enterprise_id: str
    period_year: int
    period_month: int
    sales_amount_excl_tax: str
    tax_rate: str
    tax_amount: str
    surcharge_detail: dict
    total_tax_and_surcharge: str


class CITCalculateResponse(BaseModel):
    """企业所得税计算响应"""
    enterprise_id: str
    period_year: int
    period_month: int
    taxable_income: str
    tax_rate: str
    tax_amount: str


class FullTaxCalculateResponse(BaseModel):
    """完整税务计算响应"""
    enterprise_id: str
    period_year: int
    period_month: int
    taxpayer_type: str
    vat_result: Optional[dict] = None
    cit_result: Optional[dict] = None
    total_tax: str


# ============ API Routes ============

@router.post("/vat/calculate", response_model=VATCalculateResponse)
async def calculate_vat_tax(request: VATCalculateRequest):
    """
    计算增值税及附加税

    - **enterprise_id**: 企业ID
    - **period_year/month**: 申报期间
    - **taxpayer_type**: 纳税人类型 (GENERAL/SMALL)
    - **sales_amount**: 销售收入金额
    - **tax_amount**: 增值税计算基础（根据tax_amount_is_tax_included参数决定是含税还是不含税）
    - **tax_amount_is_tax_included**: True=tax_amount是不含税销售额，False=tax_amount是含税销售额
    """
    try:
        input_data = TaxCalculationInput(
            enterprise_id=request.enterprise_id,
            taxpayer_type=TaxpayerType(request.taxpayer_type),
            sales_amount=request.sales_amount,
            tax_amount=request.tax_amount,
            tax_amount_is_tax_included=request.tax_amount_is_tax_included,
            province=Province.JIANGSU
        )

        result = calculate_vat(input_data)

        return VATCalculateResponse(
            enterprise_id=request.enterprise_id,
            period_year=request.period_year,
            period_month=request.period_month,
            sales_amount_excl_tax=f"{result.sales_amount_excl_tax:.2f}",
            tax_rate=f"{float(result.tax_rate)*100:.0f}%",
            tax_amount=f"{result.tax_amount:.2f}",
            surcharge_detail={
                "urban_construction_tax": f"{result.surcharge_detail.urban_construction:.2f}",
                "education_surcharge": f"{result.surcharge_detail.education:.2f}",
                "local_education_surcharge": f"{result.surcharge_detail.local_education:.2f}",
                "total": f"{result.surcharge_detail.total:.2f}"
            },
            total_tax_and_surcharge=f"{result.total_tax_and_surcharge:.2f}"
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/cit/calculate", response_model=CITCalculateResponse)
async def calculate_cit_tax(request: CITCalculateRequest):
    """
    计算企业所得税

    - **enterprise_id**: 企业ID
    - **period_year/month**: 申报期间
    - **taxable_income**: 应纳税所得额
    - **is_high_tech**: 是否高新技术企业
    - **is_small_low_profit**: 是否小型微利企业
    """
    try:
        result = calculate_cit(
            income=request.taxable_income,
            is_high_tech=request.is_high_tech,
            is_small_low_profit=request.is_small_low_profit
        )

        return CITCalculateResponse(
            enterprise_id=request.enterprise_id,
            period_year=request.period_year,
            period_month=request.period_month,
            taxable_income=f"{result.taxable_income:.2f}",
            tax_rate=f"{float(result.tax_rate)*100:.1f}%",
            tax_amount=f"{result.tax_amount:.2f}"
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/calculate/full", response_model=FullTaxCalculateResponse)
async def calculate_full_tax_handler(request: FullTaxCalculateRequest):
    """
    计算完整税务（增值税 + 附加税 + 企业所得税）

    - **enterprise_id**: 企业ID
    - **period_year/month**: 申报期间
    - **taxpayer_type**: 纳税人类型
    - **sales_amount**: 销售收入
    - **tax_amount**: 增值税计算基础
    - **tax_amount_is_tax_included**: True=不含税, False=含税
    - **taxable_income**: 应纳税所得额（可选，用于企业所得税计算）
    - **is_high_tech**: 是否高新技术企业
    - **is_small_low_profit**: 是否小型微利企业
    """
    try:
        input_data = TaxCalculationInput(
            enterprise_id=request.enterprise_id,
            taxpayer_type=TaxpayerType(request.taxpayer_type),
            sales_amount=request.sales_amount,
            tax_amount=request.tax_amount,
            tax_amount_is_tax_included=request.tax_amount_is_tax_included,
            province=Province.JIANGSU,
            is_high_tech=request.is_high_tech,
            is_small_low_profit=request.is_small_low_profit
        )

        result = calculate_full_tax(
            input_data=input_data,
            period_year=request.period_year,
            period_month=request.period_month
        )

        response = FullTaxCalculateResponse(
            enterprise_id=result.enterprise_id,
            period_year=result.period_year,
            period_month=result.period_month,
            taxpayer_type=result.taxpayer_type.value,
            total_tax=f"{result.total_tax:.2f}"
        )

        if result.vat_result:
            response.vat_result = {
                "sales_amount_excl_tax": f"{result.vat_result.sales_amount_excl_tax:.2f}",
                "tax_rate": f"{float(result.vat_result.tax_rate)*100:.0f}%",
                "tax_amount": f"{result.vat_result.tax_amount:.2f}",
                "surcharge_detail": {
                    "urban_construction_tax": f"{result.vat_result.surcharge_detail.urban_construction:.2f}",
                    "education_surcharge": f"{result.vat_result.surcharge_detail.education:.2f}",
                    "local_education_surcharge": f"{result.vat_result.surcharge_detail.local_education:.2f}",
                    "total": f"{result.vat_result.surcharge_detail.total:.2f}"
                },
                "total_tax_and_surcharge": f"{result.vat_result.total_tax_and_surcharge:.2f}"
            }

        if result.cit_result:
            response.cit_result = {
                "taxable_income": f"{result.cit_result.taxable_income:.2f}",
                "tax_rate": f"{float(result.cit_result.tax_rate)*100:.1f}%",
                "tax_amount": f"{result.cit_result.tax_amount:.2f}"
            }

        return response
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/vat/{enterprise_id}")
async def get_vat_records(
    enterprise_id: str,
    period_year: Optional[int] = Query(None),
    period_month: Optional[int] = Query(None)
):
    """
    获取企业增值税申报记录

    - **enterprise_id**: 企业ID
    - **period_year**: 申报年份（可选）
    - **period_month**: 申报月份（可选）
    """
    # 模拟数据，实际应从数据库查询
    mock_records = [
        {
            "id": "vat-001",
            "enterprise_id": enterprise_id,
            "period_year": 2026,
            "period_month": 3,
            "taxpayer_type": "GENERAL",
            "sales_amount": "1234567.00",
            "tax_amount": "160493.71",
            "surcharge_amount": "19259.24",
            "total_tax": "179752.95",
            "status": "CONFIRMED",
            "created_at": "2026-04-05T10:30:00Z"
        },
        {
            "id": "vat-002",
            "enterprise_id": enterprise_id,
            "period_year": 2026,
            "period_month": 4,
            "taxpayer_type": "GENERAL",
            "sales_amount": "1456789.00",
            "tax_amount": "189382.57",
            "surcharge_amount": "22725.91",
            "total_tax": "212108.48",
            "status": "DRAFT",
            "created_at": "2026-05-07T14:22:00Z"
        }
    ]

    # Filter by period if provided
    if period_year:
        mock_records = [r for r in mock_records if r["period_year"] == period_year]
    if period_month:
        mock_records = [r for r in mock_records if r["period_month"] == period_month]

    return {"items": mock_records, "total": len(mock_records)}


@router.get("/vat/{enterprise_id}/export")
async def export_vat_excel(enterprise_id: str, period_year: int, period_month: int):
    """
    导出增值税申报Excel（税务局格式）

    - **enterprise_id**: 企业ID
    - **period_year**: 申报年份
    - **period_month**: 申报月份
    """
    # 返回Excel下载链接
    return {
        "download_url": f"/api/files/vat/{enterprise_id}/{period_year}{period_month:02d}.xlsx",
        "file_name": f"增值税申报_{enterprise_id}_{period_year}{period_month:02d}.xlsx",
        "expires_at": "2026-05-10T00:00:00Z"
    }