"""
Enterprise Management Router - CRUD for enterprises using JSONStore.
"""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.storage.manager import enterprise_store, health_report_store, invoice_store, bank_transaction_store
from backend.core.config import settings
from backend.routers.auth import get_current_user
from backend.services.health_report_template import build_data_completeness
from backend.schemas.enterprise import (
    EnterpriseCreate, EnterpriseUpdate, EnterpriseResponse,
    EnterpriseListResponse, EnterpriseListItem, EnterpriseStatus
)

router = APIRouter(prefix="/api/enterprises", tags=["enterprises"])


def _to_decimal(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _get_latest_report(enterprise_id: str) -> Optional[dict]:
    """Get latest health report for an enterprise."""
    reports = health_report_store.filter(
        limit=1, order_by="analysis_date", order_desc=True,
        enterprise_id=enterprise_id
    )
    return reports[0] if reports else None


@router.get("", response_model=EnterpriseListResponse)
async def list_enterprises(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    current_user: dict = Depends(get_current_user),
):
    """List enterprises with pagination, filtering, and sorting."""
    filters = {}
    if search:
        filters["name"] = search
    if status:
        filters["status"] = status
    if source:
        filters["source"] = source

    all_enterprises = enterprise_store.filter(
        order_by=sort_by, order_desc=(sort_order == "desc")
    )

    # Apply search filter (ilike for name)
    if search:
        all_enterprises = [e for e in all_enterprises if search.lower() in e.get("name", "").lower()]

    # Apply status/source filters
    if status:
        all_enterprises = [e for e in all_enterprises if e.get("status") == status]
    if source:
        all_enterprises = [e for e in all_enterprises if e.get("source") == source]

    total = len(all_enterprises)

    # Apply pagination
    offset = (page - 1) * page_size
    enterprises = all_enterprises[offset:offset + page_size]

    items = []
    for ent in enterprises:
        report = _get_latest_report(str(ent.get("id")))
        items.append(EnterpriseListItem(
            id=str(ent.get("id")),
            name=ent.get("name"),
            industry=ent.get("industry"),
            financing_score=report.get("financing_score") if report else None,
            last_analysis_date=report.get("analysis_date") if report else None,
            status=EnterpriseStatus(ent.get("status", "ACTIVE")),
            source=ent.get("source", "DIRECT"),
        ))

    return EnterpriseListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.post("", response_model=EnterpriseResponse)
async def create_enterprise(
    req: EnterpriseCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a new enterprise."""
    # Check if tax number already exists
    existing = enterprise_store.first(tax_number=req.tax_number)
    if existing:
        raise HTTPException(status_code=400, detail="Tax number already registered")

    data = {
        "id": str(uuid.uuid4()),
        "name": req.name,
        "tax_number": req.tax_number,
        "taxpayer_type": req.taxpayer_type.value if hasattr(req.taxpayer_type, 'value') else req.taxpayer_type,
        "industry": req.industry,
        "registered_capital_range": req.registered_capital_range,
        "founded_year": req.founded_year,
        "province": req.province,
        "city": req.city,
        "source": req.source.value if hasattr(req.source, 'value') else req.source,
        "assigned_operator_id": req.assigned_operator_id,
        "status": EnterpriseStatus.ACTIVE.value,
        "channel_id": settings.DEFAULT_CHANNEL_ID,
    }

    enterprise = enterprise_store.create(**data)
    return EnterpriseResponse(
        id=enterprise["id"],
        name=enterprise["name"],
        tax_number=enterprise["tax_number"],
        taxpayer_type=enterprise["taxpayer_type"],
        industry=enterprise["industry"],
        province=enterprise["province"],
        city=enterprise["city"],
        source=enterprise["source"],
        status=EnterpriseStatus(enterprise["status"]),
        channel_id=enterprise["channel_id"],
        created_at=enterprise["created_at"],
        updated_at=enterprise["updated_at"],
    )


@router.get("/{enterprise_id}", response_model=EnterpriseResponse)
async def get_enterprise(
    enterprise_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get enterprise details by ID."""
    enterprise = enterprise_store.get_by_id(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    return EnterpriseResponse(
        id=enterprise["id"],
        name=enterprise["name"],
        tax_number=enterprise["tax_number"],
        taxpayer_type=enterprise["taxpayer_type"],
        industry=enterprise["industry"],
        province=enterprise["province"],
        city=enterprise["city"],
        source=enterprise["source"],
        status=EnterpriseStatus(enterprise["status"]),
        channel_id=enterprise["channel_id"],
        assigned_operator_id=enterprise.get("assigned_operator_id"),
        created_at=enterprise["created_at"],
        updated_at=enterprise["updated_at"],
    )


@router.put("/{enterprise_id}", response_model=EnterpriseResponse)
async def update_enterprise(
    enterprise_id: str,
    req: EnterpriseUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update enterprise information."""
    enterprise = enterprise_store.get_by_id(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.tax_number is not None:
        updates["tax_number"] = req.tax_number
    if req.taxpayer_type is not None:
        updates["taxpayer_type"] = req.taxpayer_type.value if hasattr(req.taxpayer_type, 'value') else req.taxpayer_type
    if req.industry is not None:
        updates["industry"] = req.industry
    if req.registered_capital_range is not None:
        updates["registered_capital_range"] = req.registered_capital_range
    if req.founded_year is not None:
        updates["founded_year"] = req.founded_year
    if req.province is not None:
        updates["province"] = req.province
    if req.city is not None:
        updates["city"] = req.city
    if req.source is not None:
        updates["source"] = req.source.value if hasattr(req.source, 'value') else req.source
    if req.status is not None:
        updates["status"] = req.status.value if hasattr(req.status, 'value') else req.status

    updated = enterprise_store.update(enterprise_id, **updates)
    return EnterpriseResponse(
        id=updated["id"],
        name=updated["name"],
        tax_number=updated["tax_number"],
        taxpayer_type=updated["taxpayer_type"],
        industry=updated["industry"],
        province=updated["province"],
        city=updated["city"],
        source=updated["source"],
        status=EnterpriseStatus(updated["status"]),
        channel_id=updated["channel_id"],
        assigned_operator_id=updated.get("assigned_operator_id"),
        created_at=updated["created_at"],
        updated_at=updated["updated_at"],
    )


@router.delete("/{enterprise_id}")
async def delete_enterprise(
    enterprise_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete an enterprise."""
    enterprise = enterprise_store.get_by_id(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    enterprise_store.delete(enterprise_id)
    return {"message": "Enterprise deleted successfully"}


@router.get("/{enterprise_id}/summary")
async def get_enterprise_summary(
    enterprise_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get enterprise summary statistics."""
    enterprise = enterprise_store.get_by_id(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    invoice_count = len(invoice_store.filter(enterprise_id=enterprise_id))
    tx_count = len(bank_transaction_store.filter(enterprise_id=enterprise_id))
    report = _get_latest_report(enterprise_id)

    return {
        "enterprise_id": enterprise_id,
        "enterprise_name": enterprise.get("name"),
        "invoice_count": invoice_count,
        "transaction_count": tx_count,
        "latest_report_id": report.get("id") if report else None,
        "latest_report_score": report.get("overall_score") if report else None,
        "latest_report_date": report.get("analysis_date") if report else None,
    }


@router.get("/{enterprise_id}/financials")
async def get_enterprise_financials(
    enterprise_id: str,
    period_year: Optional[int] = Query(None),
    period_month: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """Get enterprise financial detail for the operator detail drawer."""
    enterprise = enterprise_store.get_by_id(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    invoices = invoice_store.filter(enterprise_id=enterprise_id)
    transactions = [
        tx for tx in bank_transaction_store.filter(enterprise_id=enterprise_id)
        if tx.get("status") != "DELETED"
    ]
    reports = health_report_store.filter(enterprise_id=enterprise_id)

    if period_year and period_month:
        prefix = f"{period_year:04d}-{period_month:02d}"
        invoices = [inv for inv in invoices if str(inv.get("issue_date", "")).startswith(prefix)]
        transactions = [tx for tx in transactions if str(tx.get("transaction_date", "")).startswith(prefix)]
        reports = [
            report for report in reports
            if report.get("period_year") == period_year and report.get("period_month") == period_month
        ]

    months = sorted(
        {
            str(item.get("transaction_date", ""))[:7]
            for item in transactions
            if item.get("transaction_date")
        }
        | {
            str(item.get("issue_date", ""))[:7]
            for item in invoices
            if item.get("issue_date")
        }
        | {
            f"{item.get('period_year'):04d}-{item.get('period_month'):02d}"
            for item in reports
            if item.get("period_year") and item.get("period_month")
        },
        reverse=True,
    )

    monthly_summaries = []
    for month in months:
        try:
            month_year, month_number = (int(part) for part in month.split("-", 1))
        except ValueError:
            continue
        month_txs = [tx for tx in transactions if str(tx.get("transaction_date", "")).startswith(month)]
        month_invoices = [inv for inv in invoices if str(inv.get("issue_date", "")).startswith(month)]
        valid_month_invoices = [inv for inv in month_invoices if inv.get("invoice_status") != "VOID"]
        sales_invoices = [
            inv for inv in valid_month_invoices
            if (inv.get("direction") or inv.get("invoice_type")) in {"SALES", "OUTPUT"}
        ]
        purchase_invoices = [
            inv for inv in valid_month_invoices
            if (inv.get("direction") or inv.get("invoice_type")) in {"PURCHASE", "INPUT"}
        ]
        cash_inflow = sum((_to_decimal(tx.get("credit_amount")) for tx in month_txs), Decimal("0"))
        cash_outflow = sum((_to_decimal(tx.get("debit_amount")) for tx in month_txs), Decimal("0"))
        invoice_amount = sum((_to_decimal(inv.get("total_amount")) for inv in month_invoices), Decimal("0"))
        sales_amount = sum((_to_decimal(inv.get("amount")) for inv in sales_invoices), Decimal("0"))
        purchase_amount = sum((_to_decimal(inv.get("amount")) for inv in purchase_invoices), Decimal("0"))
        completeness = build_data_completeness(enterprise_id, month_year, month_number)
        latest_report = next(
            (
                report for report in reports
                if f"{report.get('period_year'):04d}-{report.get('period_month'):02d}" == month
            ),
            None,
        )

        monthly_summaries.append(
            {
                "period": month,
                "cash_inflow": _money(cash_inflow),
                "cash_outflow": _money(cash_outflow),
                "net_cash_flow": _money(cash_inflow - cash_outflow),
                "transaction_count": len(month_txs),
                "invoice_count": len(month_invoices),
                "sales_invoice_count": len(sales_invoices),
                "purchase_invoice_count": len(purchase_invoices),
                "invoice_amount": _money(invoice_amount),
                "sales_amount": _money(sales_amount),
                "purchase_amount": _money(purchase_amount),
                "data_completion_rate": completeness.get("completion_rate", 0),
                "data_ready_count": completeness.get("ready_count", 0),
                "data_total_count": completeness.get("total_count", 0),
                "data_items": completeness.get("items", []),
                "report_id": latest_report.get("report_id") if latest_report else None,
                "overall_score": latest_report.get("overall_score") if latest_report else None,
                "financing_score": latest_report.get("financing_score") if latest_report else None,
            }
        )

    total_inflow = sum((_to_decimal(tx.get("credit_amount")) for tx in transactions), Decimal("0"))
    total_outflow = sum((_to_decimal(tx.get("debit_amount")) for tx in transactions), Decimal("0"))
    recent_transactions = sorted(
        transactions,
        key=lambda tx: tx.get("transaction_date", ""),
        reverse=True,
    )[:limit]
    recent_invoices = sorted(
        invoices,
        key=lambda inv: inv.get("issue_date", ""),
        reverse=True,
    )[:limit]

    return {
        "enterprise": enterprise,
        "summary": {
            "invoice_count": len(invoices),
            "transaction_count": len(transactions),
            "report_count": len(reports),
            "cash_inflow": _money(total_inflow),
            "cash_outflow": _money(total_outflow),
            "net_cash_flow": _money(total_inflow - total_outflow),
        },
        "monthly_summaries": monthly_summaries,
        "recent_transactions": recent_transactions,
        "recent_invoices": recent_invoices,
        "reports": sorted(
            reports,
            key=lambda report: (report.get("period_year", 0), report.get("period_month", 0), report.get("created_at", "")),
            reverse=True,
        ),
    }
