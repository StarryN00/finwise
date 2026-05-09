"""
Dashboard Router - global summary statistics for operators.
Uses JSONStore for persistence.
"""
from fastapi import APIRouter

from backend.storage.manager import (
    enterprise_store,
    invoice_store,
    bank_transaction_store,
    health_report_store,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def dashboard_summary():
    """
    Get global dashboard summary.
    Returns enterprise counts, pending tasks, health report stats,
    industry distribution, and enterprise status distribution.
    """
    enterprises = enterprise_store.get_all()
    total_enterprises = len(enterprises)

    # Pending enterprises: those with pending invoices or pending transactions
    pending_eids = set()
    for inv in invoice_store.filter(status="PENDING"):
        eid = inv.get("enterprise_id")
        if eid:
            pending_eids.add(eid)
    for tx in bank_transaction_store.filter(status="PENDING"):
        eid = tx.get("enterprise_id")
        if eid:
            pending_eids.add(eid)

    # Health reports
    reports = health_report_store.get_all()
    report_count = len(reports)

    avg_score = None
    if reports:
        scores = [
            r.get("overall_score", 0)
            for r in reports
            if r.get("overall_score") is not None
        ]
        if scores:
            avg_score = round(sum(scores) / len(scores), 2)

    # Industry distribution
    industry_distribution = {}
    for ent in enterprises:
        industry = ent.get("industry") or "未知"
        industry_distribution[industry] = industry_distribution.get(industry, 0) + 1

    # Status distribution (ensure ACTIVE/SUSPENDED/CANCELLED keys exist)
    status_distribution = {"ACTIVE": 0, "SUSPENDED": 0, "CANCELLED": 0}
    for ent in enterprises:
        s = ent.get("status", "ACTIVE")
        if s in status_distribution:
            status_distribution[s] += 1
        else:
            # Map unknown statuses to ACTIVE bucket for now
            status_distribution["ACTIVE"] += 1

    return {
        "total_enterprises": total_enterprises,
        "pending_enterprises": len(pending_eids),
        "report_count": report_count,
        "average_health_score": avg_score,
        "industry_distribution": industry_distribution,
        "status_distribution": status_distribution,
    }
