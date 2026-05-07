# Report Generation API
# 三类报告生成: VAT申报报告、财务健康分析报告、融资评分报告

from datetime import date
from decimal import Decimal
from typing import List, Optional, Dict, Any
from uuid import uuid4, UUID
from enum import Enum
from pydantic import BaseModel
import json


class ReportType(str, Enum):
    VAT_FILING = "VAT_FILING"           # 增值税申报报告
    HEALTH_ANALYSIS = "HEALTH_ANALYSIS" # 财务健康分析报告
    FINANCING_SCORE = "FINANCING_SCORE" # 融资评分报告


class ReportFormat(str, Enum):
    JSON = "JSON"
    HTML = "HTML"
    PDF = "PDF"
    EXCEL = "EXCEL"


class VATFilingReportData(BaseModel):
    """增值税申报报告数据"""
    filing_id: str
    enterprise_id: str
    enterprise_name: str
    period_year: int
    period_month: int
    taxpayer_type: str
    # 销售额数据
    sales_amount_excl_tax: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    # 附加税明细
    urban_construction_tax: Decimal
    education_surcharge: Decimal
    local_education_surcharge: Decimal
    total_surcharge: Decimal
    # 合计
    total_tax_and_surcharge: Decimal
    # 申报状态
    status: str
    created_at: str


class HealthAnalysisReportData(BaseModel):
    """财务健康分析报告数据"""
    report_id: str
    report_number: str
    enterprise_id: str
    enterprise_name: str
    analysis_date: str
    # 总体评分
    overall_score: int
    overall_grade: str
    # 五维度评分
    profitability_score: float
    solvency_score: float
    operation_efficiency_score: float
    growth_score: float
    cash_flow_score: float
    # 雷达图数据
    radar_data: Dict[str, float]
    # 关键指标
    key_metrics: Dict[str, Any]
    # AI解读
    ai_interpretation: str
    # 风险提示
    risk_alerts: List[str]
    # 改进建议
    improvement_suggestions: List[str]
    # 融资相关信息
    financing_score: int
    estimated_loan_amount: Optional[Decimal] = None
    matched_products: List[str]
    # 报告状态
    status: str
    created_at: str


class FinancingScoreReportData(BaseModel):
    """融资评分报告数据"""
    score_id: str
    enterprise_id: str
    enterprise_name: str
    score_date: str
    # 评分结果
    score: int
    level: str  # HIGH | MEDIUM | LOW
    estimated_loan_amount: Decimal
    # 匹配的融资产品
    matched_products: List[Dict[str, Any]]
    # 评分因素
    scoring_factors: List[Dict[str, Any]]
    # 分析摘要
    analysis_summary: str
    created_at: str


class ReportGenerationRequest(BaseModel):
    """报告生成请求"""
    report_type: ReportType
    enterprise_id: str
    format: ReportFormat = ReportFormat.JSON
    period_year: Optional[int] = None
    period_month: Optional[int] = None
    options: Optional[Dict[str, Any]] = None


class ReportGenerationResponse(BaseModel):
    """报告生成响应"""
    report_id: str
    status: str
    download_url: Optional[str] = None
    preview_data: Optional[Dict[str, Any]] = None


class ReportGenerator:
    """
    报告生成器
    支持生成三类报告: VAT申报、财务健康分析、融资评分
    """

    def __init__(self):
        self._reports_cache: Dict[str, Any] = {}

    def generate_vat_report(self, enterprise_id: str, period_year: int, period_month: int) -> Dict[str, Any]:
        """
        生成增值税申报报告 JSON
        """
        report_id = str(uuid4())

        # 模拟从数据库获取数据
        report_data = {
            "report_id": report_id,
            "report_type": "VAT_FILING",
            "enterprise_id": enterprise_id,
            "enterprise_name": "昆山某某科技有限公司",  # 实际应从DB获取
            "period_year": period_year,
            "period_month": period_month,
            "taxpayer_type": "GENERAL",
            "sales_amount_excl_tax": "1,234,567.00",
            "tax_rate": "13%",
            "tax_amount": "160,493.71",
            "surcharge_details": {
                "urban_construction_tax": "11,234.56",
                "education_surcharge": "4,814.81",
                "local_education_surcharge": "3,209.87"
            },
            "total_surcharge": "19,259.24",
            "total_tax_and_surcharge": "179,752.95",
            "status": "DRAFT",
            "created_at": date.today().isoformat(),
            "summary": {
                "total_sales": "1,234,567.00",
                "total_vat": "160,493.71",
                "total_surcharge": "19,259.24",
                "grand_total": "179,752.95"
            }
        }

        self._reports_cache[report_id] = report_data
        return report_data

    def generate_health_report(self, enterprise_id: str, report_type: str = "FULL") -> Dict[str, Any]:
        """
        生成财务健康分析报告 JSON
        """
        report_id = str(uuid4())
        report_number = f"HR-{date.today().year}-{report_id[:8].upper()}"

        report_data = {
            "report_id": report_id,
            "report_number": report_number,
            "report_type": "HEALTH_ANALYSIS",
            "enterprise_id": enterprise_id,
            "enterprise_name": "昆山某某科技有限公司",
            "analysis_date": date.today().isoformat(),
            "overall_score": 78,
            "overall_grade": "B_PLUS",
            "five_dimension_scores": {
                "profitability": {
                    "score": 82.5,
                    "weight": 0.25,
                    "description": "盈利能力良好"
                },
                "solvency": {
                    "score": 75.0,
                    "weight": 0.20,
                    "description": "偿债能力中等"
                },
                "operation_efficiency": {
                    "score": 80.0,
                    "weight": 0.20,
                    "description": "运营效率较高"
                },
                "growth": {
                    "score": 72.5,
                    "weight": 0.20,
                    "description": "增长潜力一般"
                },
                "cash_flow": {
                    "score": 85.0,
                    "weight": 0.15,
                    "description": "现金流状况优秀"
                }
            },
            "radar_data": {
                "profitability": 82.5,
                "solvency": 75.0,
                "operation_efficiency": 80.0,
                "growth": 72.5,
                "cash_flow": 85.0
            },
            "key_metrics": {
                "gross_margin": "28.5%",
                "net_margin": "12.3%",
                "roa": "8.7%",
                "roe": "15.2%",
                "current_ratio": 1.85,
                "quick_ratio": 1.42,
                "inventory_turnover": 4.5,
                "receivable_turnover": 6.2,
                "revenue_growth_yoy": "15.3%",
                "profit_growth_yoy": "22.1%",
                "operating_cash_flow": 2_450_000,
                "free_cash_flow": 1_850_000
            },
            "ai_interpretation": "该公司整体财务状况良好，现金流充裕，盈利能力较强。建议关注应收账款周转情况，适当优化负债结构以进一步提升评级。",
            "risk_alerts": [
                "应收账款周转天数同比增加12天",
                "存货周转率略低于行业平均水平",
                "短期负债占比偏高"
            ],
            "improvement_suggestions": [
                "加强客户信用管理，缩短应收账款账期",
                "优化库存管理，提高存货周转率",
                "适度增加长期融资，降低短期偿债压力"
            ],
            "financing_score": 82,
            "estimated_loan_amount": 5_000_000,
            "matched_products": [
                "税易贷-A",
                "经营贷-优质客户专享",
                "供应链金融-核心企业"
            ],
            "status": "COMPLETED",
            "created_at": date.today().isoformat()
        }

        self._reports_cache[report_id] = report_data
        return report_data

    def generate_financing_score_report(self, enterprise_id: str) -> Dict[str, Any]:
        """
        生成融资评分报告 JSON
        """
        score_id = str(uuid4())

        report_data = {
            "score_id": score_id,
            "report_type": "FINANCING_SCORE",
            "enterprise_id": enterprise_id,
            "enterprise_name": "昆山某某科技有限公司",
            "score_date": date.today().isoformat(),
            "score": 82,
            "level": "HIGH",
            "score_grade": "A",
            "estimated_loan_amount": 5_000_000,
            "loan_amount_range": {
                "min": 3_000_000,
                "max": 8_000_000
            },
            "matched_products": [
                {
                    "product_id": "P001",
                    "product_name": "税易贷-A",
                    "max_amount": 5_000_000,
                    "interest_rate_range": "4.35% - 7.20%",
                    "loan_term": "12-36个月",
                    "basic_requirements": [
                        "企业成立满2年",
                        "纳税信用等级B级以上",
                        "年营业收入500万以上"
                    ]
                },
                {
                    "product_id": "P002",
                    "product_name": "经营贷-优质客户专享",
                    "max_amount": 8_000_000,
                    "interest_rate_range": "5.50% - 9.80%",
                    "loan_term": "6-60个月",
                    "basic_requirements": [
                        "企业成立满1年",
                        "有固定经营场所",
                        "信用记录良好"
                    ]
                }
            ],
            "scoring_factors": [
                {
                    "factor": "纳税信用",
                    "weight": 0.25,
                    "score": 88,
                    "description": "纳税信用等级B级，表现良好"
                },
                {
                    "factor": "财务健康度",
                    "weight": 0.30,
                    "score": 82,
                    "description": "综合财务指标良好，盈利能力较强"
                },
                {
                    "factor": "经营稳定性",
                    "weight": 0.20,
                    "score": 78,
                    "description": "经营年限较长，业务结构稳定"
                },
                {
                    "factor": "现金流状况",
                    "weight": 0.15,
                    "score": 90,
                    "description": "经营现金流充裕，偿债能力强"
                },
                {
                    "factor": "企业信用记录",
                    "weight": 0.10,
                    "score": 75,
                    "description": "无不良信用记录，整体信用良好"
                }
            ],
            "analysis_summary": "该企业综合评分82分，达到A级标准。建议申请税易贷-A产品，最高可获500万元贷款，利率4.35%起。",
            "risk_factors": [
                "行业周期风险",
                "应收账款集中度"
            ],
            "recommendations": [
                "建议保持良好纳税记录，争取提升至A级纳税人",
                "适度分散客户结构，降低应收账款集中度",
                "关注现金流管理，保持健康的现金储备"
            ],
            "created_at": date.today().isoformat()
        }

        self._reports_cache[score_id] = report_data
        return report_data

    def generate_report(self, request: ReportGenerationRequest) -> Dict[str, Any]:
        """
        统一报告生成入口
        """
        if request.report_type == ReportType.VAT_FILING:
            return self.generate_vat_report(
                enterprise_id=request.enterprise_id,
                period_year=request.period_year or date.today().year,
                period_month=request.period_month or date.today().month
            )
        elif request.report_type == ReportType.HEALTH_ANALYSIS:
            return self.generate_health_report(
                enterprise_id=request.enterprise_id,
                report_type=request.options.get("report_type", "FULL") if request.options else "FULL"
            )
        elif request.report_type == ReportType.FINANCING_SCORE:
            return self.generate_financing_score_report(
                enterprise_id=request.enterprise_id
            )
        else:
            raise ValueError(f"Unknown report type: {request.report_type}")

    def export_to_format(self, report_id: str, format: ReportFormat) -> str:
        """
        导出报告为指定格式
        目前返回文件路径（PDF/HTML/Excel需后续实现文件生成逻辑）
        """
        if report_id not in self._reports_cache:
            raise ValueError(f"Report {report_id} not found")

        if format == ReportFormat.JSON:
            return json.dumps(self._reports_cache[report_id], indent=2, ensure_ascii=False)
        elif format == ReportFormat.HTML:
            return self._generate_html_report(report_id)
        elif format == ReportFormat.PDF:
            return f"/api/files/reports/{report_id}.pdf"
        elif format == ReportFormat.EXCEL:
            return f"/api/files/reports/{report_id}.xlsx"
        else:
            raise ValueError(f"Unsupported format: {format}")

    def _generate_html_report(self, report_id: str) -> str:
        """生成HTML格式报告"""
        report_data = self._reports_cache.get(report_id, {})
        report_type = report_data.get("report_type", "UNKNOWN")

        html_template = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{report_type} - 报告</title>
    <style>
        body {{ font-family: "Microsoft YaHei", Arial, sans-serif; margin: 40px; }}
        .report-header {{ text-align: center; margin-bottom: 30px; }}
        .report-title {{ font-size: 24px; font-weight: bold; }}
        .section {{ margin: 20px 0; }}
        .section-title {{ font-size: 16px; font-weight: bold; border-bottom: 1px solid #333; padding-bottom: 5px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f5f5f5; }}
    </style>
</head>
<body>
    <div class="report-header">
        <div class="report-title">{report_type}报告</div>
        <div>企业: {report_data.get('enterprise_name', 'N/A')}</div>
        <div>生成日期: {report_data.get('created_at', date.today().isoformat())}</div>
    </div>
    <div class="section">
        <pre>{json.dumps(report_data, indent=2, ensure_ascii=False)}</pre>
    </div>
</body>
</html>"""
        return html_template


# 全局报告生成器实例
report_generator = ReportGenerator()


def generate_vat_report(enterprise_id: str, period_year: int, period_month: int) -> Dict[str, Any]:
    """快捷函数：生成VAT申报报告"""
    return report_generator.generate_vat_report(enterprise_id, period_year, period_month)


def generate_health_report(enterprise_id: str, report_type: str = "FULL") -> Dict[str, Any]:
    """快捷函数：生成财务健康分析报告"""
    return report_generator.generate_health_report(enterprise_id, report_type)


def generate_financing_score_report(enterprise_id: str) -> Dict[str, Any]:
    """快捷函数：生成融资评分报告"""
    return report_generator.generate_financing_score_report(enterprise_id)