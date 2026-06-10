# Report Generation API
# 三类报告生成: VAT申报报告、财务健康分析报告、融资评分报告

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Dict, Any
from uuid import uuid4, UUID
from enum import Enum
from pydantic import BaseModel
import json
import asyncio

from backend.storage.manager import (
    invoice_store,
    bank_transaction_store,
    enterprise_store,
    vat_filing_store,
    health_report_store,
)
from backend.tax.calculator import (
    calculate_vat,
    TaxCalculationInput,
    TaxpayerType,
)
from backend.services.health_report_template import build_financial_health_report, save_financial_health_report


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


# ============ Helper Functions (outside ReportGenerator class) ============

def _aggregate_invoice_data(enterprise_id: str, period_year: int, period_month: int) -> dict:
    """
    Aggregate invoice data for a given enterprise and period.
    Returns dict with sales (销项) and purchases (进项) breakdowns.
    """
    all_invoices = invoice_store.filter(enterprise_id=enterprise_id)

    # Filter by period
    period_invoices = []
    for inv in all_invoices:
        issue_date_str = inv.get('issue_date', '')
        if not issue_date_str:
            continue
        try:
            dt = datetime.fromisoformat(issue_date_str.replace('Z', '+00:00'))
            if dt.year == period_year and dt.month == period_month:
                period_invoices.append(inv)
        except (ValueError, TypeError):
            # Try parsing as date only
            try:
                dt = datetime.strptime(issue_date_str[:10], '%Y-%m-%d')
                if dt.year == period_year and dt.month == period_month:
                    period_invoices.append(inv)
            except ValueError:
                continue

    valid_invoices = [inv for inv in period_invoices if inv.get('invoice_status') != 'VOID']
    sales_invoices = [
        inv for inv in valid_invoices
        if (inv.get('direction') or inv.get('invoice_type')) in {'SALES', 'OUTPUT'}
    ]
    purchase_invoices = [
        inv for inv in valid_invoices
        if (inv.get('direction') or inv.get('invoice_type')) in {'PURCHASE', 'INPUT'}
    ]

    def sum_invoices(invoices: List[dict]) -> tuple:
        total_excl_tax = Decimal('0')
        total_tax = Decimal('0')
        count = 0
        for inv in invoices:
            amount = Decimal(str(inv.get('amount', 0) or 0))
            tax = Decimal(str(inv.get('tax_amount', 0) or 0))
            total_excl_tax += amount
            total_tax += tax
            count += 1
        return total_excl_tax, total_tax, count

    sales_excl_tax, sales_tax, sales_count = sum_invoices(sales_invoices)
    purchase_excl_tax, purchase_tax, purchase_count = sum_invoices(purchase_invoices)

    return {
        'sales_excl_tax': sales_excl_tax,
        'sales_tax': sales_tax,
        'sales_count': sales_count,
        'purchase_excl_tax': purchase_excl_tax,
        'purchase_tax': purchase_tax,
        'purchase_count': purchase_count,
        'total_count': sales_count + purchase_count,
        # Ratio for financing score
        'sales_purchase_ratio': float(sales_excl_tax / purchase_excl_tax) if purchase_excl_tax > 0 else 0.0,
    }


def _aggregate_bank_transaction_data(enterprise_id: str) -> dict:
    """
    Aggregate bank transaction data for a given enterprise.
    Returns dict with inflow, outflow, net cash flow, and transaction count.
    """
    transactions = bank_transaction_store.filter(enterprise_id=enterprise_id)

    total_inflow = Decimal('0')
    total_outflow = Decimal('0')
    tx_count = len(transactions)

    for tx in transactions:
        credit = Decimal(str(tx.get('credit_amount', 0) or 0))
        debit = Decimal(str(tx.get('debit_amount', 0) or 0))
        total_inflow += credit
        total_outflow += debit

    net_cash_flow = total_inflow - total_outflow

    return {
        'total_inflow': total_inflow,
        'total_outflow': total_outflow,
        'net_cash_flow': net_cash_flow,
        'transaction_count': tx_count,
        'has_transactions': tx_count > 0,
        'positive_cash_flow': net_cash_flow > 0,
    }


# ============ ReportGenerator Class ============

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

        # Get enterprise name
        enterprise = enterprise_store.get_by_id(enterprise_id)
        enterprise_name = enterprise.get('name', '未知企业') if enterprise else '未知企业'

        # Aggregate invoice data
        invoice_data = _aggregate_invoice_data(enterprise_id, period_year, period_month)

        sales_excl_tax = invoice_data['sales_excl_tax']
        sales_tax = invoice_data['sales_tax']

        # If no real data, fall back to zeros
        if sales_excl_tax == 0 and sales_tax == 0:
            sales_amount_excl_tax = Decimal('0')
        else:
            # Use aggregated sales amount
            sales_amount_excl_tax = sales_excl_tax

        # Build tax calculation input
        # sales_amount is the excluded-tax amount (不含税金额)
        input_data = TaxCalculationInput(
            enterprise_id=enterprise_id,
            taxpayer_type=TaxpayerType.GENERAL,
            sales_amount=sales_amount_excl_tax,
            tax_amount=sales_amount_excl_tax,  # tax_amount_is_tax_included=True means this is the excluded-tax sales amount
            tax_amount_is_tax_included=True,
        )

        # Calculate VAT
        vat_result = calculate_vat(input_data)

        # Build report data
        report_data = {
            "report_id": report_id,
            "report_type": "VAT_FILING",
            "enterprise_id": enterprise_id,
            "enterprise_name": enterprise_name,
            "period_year": period_year,
            "period_month": period_month,
            "taxpayer_type": "GENERAL",
            "sales_amount_excl_tax": str(vat_result.sales_amount_excl_tax),
            "tax_rate": f"{int(vat_result.tax_rate * 100)}%",
            "tax_amount": str(vat_result.tax_amount),
            "surcharge_details": {
                "urban_construction_tax": str(vat_result.surcharge_detail.urban_construction),
                "education_surcharge": str(vat_result.surcharge_detail.education),
                "local_education_surcharge": str(vat_result.surcharge_detail.local_education)
            },
            "total_surcharge": str(vat_result.surcharge_detail.total),
            "total_tax_and_surcharge": str(vat_result.total_tax_and_surcharge),
            "status": "DRAFT",
            "created_at": datetime.utcnow().isoformat(),
            "summary": {
                "total_sales": str(vat_result.sales_amount_excl_tax),
                "total_vat": str(vat_result.tax_amount),
                "total_surcharge": str(vat_result.surcharge_detail.total),
                "grand_total": str(vat_result.total_tax_and_surcharge)
            }
        }

        self._reports_cache[report_id] = report_data

        # Store in vat_filing_store
        vat_filing_store.create(
            filing_id=report_id,
            enterprise_id=enterprise_id,
            enterprise_name=enterprise_name,
            period_year=period_year,
            period_month=period_month,
            sales_amount_excl_tax=str(vat_result.sales_amount_excl_tax),
            tax_rate=f"{int(vat_result.tax_rate * 100)}%",
            tax_amount=str(vat_result.tax_amount),
            surcharge_details=json.dumps({
                "urban_construction_tax": str(vat_result.surcharge_detail.urban_construction),
                "education_surcharge": str(vat_result.surcharge_detail.education),
                "local_education_surcharge": str(vat_result.surcharge_detail.local_education)
            }),
            total_surcharge=str(vat_result.surcharge_detail.total),
            total_tax_and_surcharge=str(vat_result.total_tax_and_surcharge),
            status="DRAFT",
            report_type="VAT_FILING",
        )

        return report_data

    def generate_health_report(self, enterprise_id: str, report_type: str = "FULL") -> Dict[str, Any]:
        """
        生成财务健康分析报告 JSON
        """
        report_id = str(uuid4())
        report_number = f"HR-{datetime.now().year}-{report_id[:8].upper()}"

        # Get enterprise name
        enterprise = enterprise_store.get_by_id(enterprise_id)
        enterprise_name = enterprise.get('name', '未知企业') if enterprise else '未知企业'

        # Aggregate real data
        invoice_data = _aggregate_invoice_data(enterprise_id, datetime.now().year, datetime.now().month)
        bank_data = _aggregate_bank_transaction_data(enterprise_id)

        # Build financial_data for AI
        financial_data = {
            "enterprise_id": enterprise_id,
            "report_date": datetime.now().isoformat(),
            "invoice_summary": {
                "sales_amount_excl_tax": float(invoice_data['sales_excl_tax']),
                "sales_tax": float(invoice_data['sales_tax']),
                "sales_invoice_count": invoice_data['sales_count'],
                "purchase_amount_excl_tax": float(invoice_data['purchase_excl_tax']),
                "purchase_tax": float(invoice_data['purchase_tax']),
                "purchase_invoice_count": invoice_data['purchase_count'],
                "total_invoice_count": invoice_data['total_count'],
                "sales_purchase_ratio": invoice_data['sales_purchase_ratio'],
            },
            "bank_summary": {
                "total_inflow": float(bank_data['total_inflow']),
                "total_outflow": float(bank_data['total_outflow']),
                "net_cash_flow": float(bank_data['net_cash_flow']),
                "transaction_count": bank_data['transaction_count'],
            }
        }

        # Call AI service (async) - use asyncio.run since this is sync context
        try:
            ai_result = asyncio.run(
                _call_generate_health_analysis_with_ai(UUID(enterprise_id), financial_data)
            )
        except Exception as e:
            # Fallback to safe mock if AI fails
            ai_result = {
                "overall_score": 50,
                "overall_grade": "C",
                "profitability_score": 50.0,
                "solvency_score": 50.0,
                "operation_efficiency_score": 50.0,
                "growth_score": 50.0,
                "cash_flow_score": 50.0,
                "radar_data": {"profitability": 50.0, "solvency": 50.0, "operation_efficiency": 50.0, "growth": 50.0, "cash_flow": 50.0},
                "key_metrics": {},
                "ai_interpretation": f"AI分析服务暂时不可用，使用默认评分。详情：{str(e)}",
                "risk_alerts": ["数据不足，无法生成完整分析"],
                "improvement_suggestions": ["请确保发票和银行流水数据完整"],
                "financing_score": 50,
                "estimated_loan_amount": 2500000,
                "matched_products": ["税易贷-A", "经营贷-优质客户专享"],
            }

        report_data = {
            "report_id": report_id,
            "report_number": report_number,
            "report_type": "HEALTH_ANALYSIS",
            "enterprise_id": enterprise_id,
            "enterprise_name": enterprise_name,
            "analysis_date": datetime.now().date().isoformat(),
            "overall_score": ai_result.get('overall_score', 50),
            "overall_grade": ai_result.get('overall_grade', 'C'),
            "five_dimension_scores": {
                "profitability": {
                    "score": ai_result.get('profitability_score', 50.0),
                    "weight": 0.25,
                    "description": "盈利能力分析"
                },
                "solvency": {
                    "score": ai_result.get('solvency_score', 50.0),
                    "weight": 0.20,
                    "description": "偿债能力分析"
                },
                "operation_efficiency": {
                    "score": ai_result.get('operation_efficiency_score', 50.0),
                    "weight": 0.20,
                    "description": "运营效率分析"
                },
                "growth": {
                    "score": ai_result.get('growth_score', 50.0),
                    "weight": 0.20,
                    "description": "成长性分析"
                },
                "cash_flow": {
                    "score": ai_result.get('cash_flow_score', 50.0),
                    "weight": 0.15,
                    "description": "现金流分析"
                }
            },
            "radar_data": ai_result.get('radar_data', {"profitability": 50.0, "solvency": 50.0, "operation_efficiency": 50.0, "growth": 50.0, "cash_flow": 50.0}),
            "key_metrics": ai_result.get('key_metrics', {}),
            "ai_interpretation": ai_result.get('ai_interpretation', ''),
            "risk_alerts": ai_result.get('risk_alerts', []),
            "improvement_suggestions": ai_result.get('improvement_suggestions', []),
            "financing_score": ai_result.get('financing_score', 50),
            "estimated_loan_amount": ai_result.get('estimated_loan_amount', 2500000),
            "matched_products": ai_result.get('matched_products', ["税易贷-A", "经营贷-优质客户专享"]),
            "status": "COMPLETED",
            "created_at": datetime.utcnow().isoformat()
        }

        self._reports_cache[report_id] = report_data

        # Store in health_report_store
        health_report_store.create(
            report_id=report_id,
            report_number=report_number,
            enterprise_id=enterprise_id,
            enterprise_name=enterprise_name,
            report_type="HEALTH_ANALYSIS",
            overall_score=ai_result.get('overall_score', 50),
            overall_grade=ai_result.get('overall_grade', 'C'),
            financing_score=ai_result.get('financing_score', 50),
            data=json.dumps(report_data),
            status="COMPLETED",
        )

        return report_data

    def generate_financing_score_report(self, enterprise_id: str) -> Dict[str, Any]:
        """
        生成融资评分报告 JSON
        """
        score_id = str(uuid4())

        # Get enterprise name
        enterprise = enterprise_store.get_by_id(enterprise_id)
        enterprise_name = enterprise.get('name', '未知企业') if enterprise else '未知企业'

        # Try to get financing_score from latest health report
        financing_score = None
        latest_health_report = None

        health_reports = health_report_store.filter(
            enterprise_id=enterprise_id,
            report_type="HEALTH_ANALYSIS",
        )
        if health_reports:
            # Sort by created_at desc, take first
            latest_health_report = health_reports[0]
            health_data_raw = latest_health_report.get('data', '{}')
            try:
                health_data = json.loads(health_data_raw)
                financing_score = health_data.get('financing_score')
            except (json.JSONDecodeError, TypeError):
                financing_score = latest_health_report.get('financing_score')

        # Calculate score if not available
        if financing_score is None:
            # Use invoice aggregation to calculate score
            invoice_data = _aggregate_invoice_data(enterprise_id, datetime.now().year, datetime.now().month)
            bank_data = _aggregate_bank_transaction_data(enterprise_id)

            score = 50  # base score
            score += min(invoice_data['total_count'] * 1, 20)  # +invoice count * 1 (max +20)
            if bank_data['has_transactions']:
                score += 10  # +10 for having bank transactions
            if bank_data['positive_cash_flow']:
                score += 10  # +10 for positive net cash flow
            if invoice_data['sales_purchase_ratio'] > 1.2:
                score += 10  # +10 for sales/purchase ratio > 1.2

            financing_score = min(score, 100)

        # Determine level
        if financing_score >= 80:
            level = "HIGH"
        elif financing_score >= 60:
            level = "MEDIUM"
        else:
            level = "LOW"

        # Calculate estimated loan amount: score * 50000, max 5 million
        estimated_loan_amount = min(financing_score * 50000, 5_000_000)

        report_data = {
            "score_id": score_id,
            "report_type": "FINANCING_SCORE",
            "enterprise_id": enterprise_id,
            "enterprise_name": enterprise_name,
            "score_date": datetime.now().date().isoformat(),
            "score": financing_score,
            "level": level,
            "score_grade": "A" if level == "HIGH" else ("B" if level == "MEDIUM" else "C"),
            "estimated_loan_amount": estimated_loan_amount,
            "loan_amount_range": {
                "min": int(estimated_loan_amount * 0.6),
                "max": int(estimated_loan_amount * 1.2)
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
                    "score": financing_score,
                    "description": "基于财务健康报告评分"
                },
                {
                    "factor": "财务健康度",
                    "weight": 0.30,
                    "score": financing_score,
                    "description": "综合财务指标评估"
                },
                {
                    "factor": "经营稳定性",
                    "weight": 0.20,
                    "score": financing_score - 5 if financing_score > 5 else financing_score,
                    "description": "经营年限和稳定性"
                },
                {
                    "factor": "现金流状况",
                    "weight": 0.15,
                    "score": financing_score,
                    "description": "银行流水分析"
                },
                {
                    "factor": "企业信用记录",
                    "weight": 0.10,
                    "score": financing_score - 10 if financing_score > 10 else financing_score,
                    "description": "信用记录评估"
                }
            ],
            "analysis_summary": f"该企业综合评分{financing_score}分，达到{level}级标准。{'建议申请税易贷-A产品' if level == 'HIGH' else '建议提升财务健康度后再申请'}，最高可获{estimated_loan_amount / 10000:.0f}万元贷款。",
            "risk_factors": [
                "行业周期风险",
                "应收账款集中度"
            ],
            "recommendations": [
                "建议保持良好纳税记录，争取提升至A级纳税人",
                "适度分散客户结构，降低应收账款集中度",
                "关注现金流管理，保持健康的现金储备"
            ],
            "created_at": datetime.utcnow().isoformat()
        }

        self._reports_cache[score_id] = report_data

        # Store in health_report_store with type FINANCING_SCORE
        health_report_store.create(
            report_id=score_id,
            enterprise_id=enterprise_id,
            enterprise_name=enterprise_name,
            report_type="FINANCING_SCORE",
            score=financing_score,
            level=level,
            estimated_loan_amount=str(estimated_loan_amount),
            data=json.dumps(report_data),
            status="COMPLETED",
        )

        return report_data

    def generate_report(self, request: ReportGenerationRequest) -> Dict[str, Any]:
        """
        统一报告生成入口
        """
        if request.report_type == ReportType.VAT_FILING:
            return self.generate_vat_report(
                enterprise_id=request.enterprise_id,
                period_year=request.period_year or datetime.now().year,
                period_month=request.period_month or datetime.now().month
            )
        elif request.report_type == ReportType.HEALTH_ANALYSIS:
            report = build_financial_health_report(
                request.enterprise_id,
                request.period_year or datetime.now().year,
                request.period_month or datetime.now().month,
            )
            return save_financial_health_report(report)
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
        <div>生成日期: {report_data.get('created_at', datetime.now().date().isoformat())}</div>
    </div>
    <div class="section">
        <pre>{json.dumps(report_data, indent=2, ensure_ascii=False)}</pre>
    </div>
</body>
</html>"""
        return html_template


# ============ Async wrapper for AI service ============

async def _call_generate_health_analysis_with_ai(enterprise_id: UUID, financial_data: Dict[str, Any]) -> Dict[str, Any]:
    """Wrapper to call the async AI service from sync context."""
    # Import here to avoid circular imports
    from backend.services.ai_service import generate_health_analysis_with_ai
    return await generate_health_analysis_with_ai(enterprise_id, financial_data)


# ============ Module-level shortcut functions ============

# Global report generator instance
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
