# Tax Calculation Engine
# Supports: VAT (增值税), Surcharges (附加税), Corporate Income Tax (企业所得税)

from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class TaxpayerType(str, Enum):
    GENERAL = "GENERAL"      # 一般纳税人
    SMALL = "SMALL"          # 小规模纳税人


class Province(str, Enum):
    JIANGSU = "JIANGSU"      # 江苏省


# 税率配置
VAT_RATES = {
    "GENERAL_STANDARD": Decimal("0.13"),      # 一般纳税人标准税率 13%
    "GENERAL_LOW": Decimal("0.09"),           # 一般纳税人低税率 9%
    "GENERAL_SIMPLE": Decimal("0.06"),         # 一般纳税人简易征收 6%
    "SMALL": Decimal("0.03"),                 # 小规模纳税人 3%
}

# 附加税税率 (以增值税为计税基础)
SURCHARGE_RATES = {
    "URBAN_CONSTRUCTION": Decimal("0.07"),     # 城市建设维护税 7%
    "EDUCATION": Decimal("0.03"),              # 教育费附加 3%
    "LOCAL_EDUCATION": Decimal("0.02"),        # 地方教育费附加 2%
}

# 企业所得税税率
CIT_RATES = {
    "STANDARD": Decimal("0.25"),              # 标准税率 25%
    "HIGH_TECH": Decimal("0.15"),             # 高新技术企业 15%
    "SMALL_LOW": Decimal("0.20"),             # 小型微利企业 20%
}


class TaxCalculationInput(BaseModel):
    """税务计算输入"""
    enterprise_id: str
    taxpayer_type: TaxpayerType
    sales_amount: Decimal          # 销售收入（含税或不含税取决于tax_amount_is_tax_included）
    tax_amount: Decimal           # 增值税税额 or 销售金额（取决于下个字段）
    tax_amount_is_tax_included: bool = True  # True=tax_amount是不含税金额，False=tax_amount是含税金额
    province: Province = Province.JIANGSU
    is_high_tech: bool = False    # 是否高新技术企业
    is_small_low_profit: bool = False  # 是否小型微利企业


class SurchargeDetail(BaseModel):
    """附加税明细"""
    urban_construction: Decimal
    education: Decimal
    local_education: Decimal
    total: Decimal


class VATCalculationResult(BaseModel):
    """增值税计算结果"""
    sales_amount_excl_tax: Decimal   # 不含税销售额
    tax_rate: Decimal               # 税率
    tax_amount: Decimal             # 增值税税额
    surcharge_detail: SurchargeDetail  # 附加税明细
    total_tax_and_surcharge: Decimal  # 增值税 + 附加税合计


class CITCalculationResult(BaseModel):
    """企业所得税计算结果"""
    taxable_income: Decimal         # 应纳税所得额
    tax_rate: Decimal               # 所得税税率
    tax_amount: Decimal             # 企业所得税税额


class TaxCalculationResult(BaseModel):
    """完整税务计算结果"""
    enterprise_id: str
    period_year: int
    period_month: int
    taxpayer_type: TaxpayerType
    vat_result: Optional[VATCalculationResult] = None
    cit_result: Optional[CITCalculationResult] = None
    total_tax: Decimal              # 总税额（增值税 + 附加税 + 企业所得税）


def calculate_vat(input_data: TaxCalculationInput) -> VATCalculationResult:
    """
    计算增值税和附加税
    """
    # 处理含税/不含税金额
    if input_data.tax_amount_is_tax_included:
        # tax_amount是不含税销售额
        sales_amount_excl_tax = input_data.tax_amount
    else:
        # tax_amount是含税销售额，需要换算
        sales_amount_excl_tax = input_data.tax_amount / (1 + _get_vat_rate(input_data.taxpayer_type))

    # 计算增值税
    tax_rate = _get_vat_rate(input_data.taxpayer_type)
    tax_amount = (sales_amount_excl_tax * tax_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # 计算附加税（以增值税为计税基础）
    urban_construction = (tax_amount * SURCHARGE_RATES["URBAN_CONSTRUCTION"]).quantize(Decimal("0.01"), ROUND_HALF_UP)
    education = (tax_amount * SURCHARGE_RATES["EDUCATION"]).quantize(Decimal("0.01"), ROUND_HALF_UP)
    local_education = (tax_amount * SURCHARGE_RATES["LOCAL_EDUCATION"]).quantize(Decimal("0.01"), ROUND_HALF_UP)

    surcharge_detail = SurchargeDetail(
        urban_construction=urban_construction,
        education=education,
        local_education=local_education,
        total=urban_construction + education + local_education
    )

    return VATCalculationResult(
        sales_amount_excl_tax=sales_amount_excl_tax,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        surcharge_detail=surcharge_detail,
        total_tax_and_surcharge=tax_amount + surcharge_detail.total
    )


def calculate_cit(income: Decimal, is_high_tech: bool = False, is_small_low_profit: bool = False) -> CITCalculationResult:
    """
    计算企业所得税
    """
    # 确定税率
    if is_high_tech:
        tax_rate = CIT_RATES["HIGH_TECH"]
    elif is_small_low_profit:
        tax_rate = CIT_RATES["SMALL_LOW"]
    else:
        tax_rate = CIT_RATES["STANDARD"]

    tax_amount = (income * tax_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)

    return CITCalculationResult(
        taxable_income=income,
        tax_rate=tax_rate,
        tax_amount=tax_amount
    )


def calculate_full_tax(input_data: TaxCalculationInput, period_year: int, period_month: int) -> TaxCalculationResult:
    """
    计算完整税务（增值税 + 附加税 + 企业所得税）
    """
    vat_result = calculate_vat(input_data)

    total_tax = vat_result.total_tax_and_surcharge
    cit_result = None

    return TaxCalculationResult(
        enterprise_id=input_data.enterprise_id,
        period_year=period_year,
        period_month=period_month,
        taxpayer_type=input_data.taxpayer_type,
        vat_result=vat_result,
        cit_result=cit_result,
        total_tax=total_tax
    )


def _get_vat_rate(taxpayer_type: TaxpayerType) -> Decimal:
    """获取增值税税率"""
    if taxpayer_type == TaxpayerType.GENERAL:
        return VAT_RATES["GENERAL_STANDARD"]
    else:
        return VAT_RATES["SMALL"]