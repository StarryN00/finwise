"""
Enterprise Management Router - CRUD for enterprises using JSONStore.
"""
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.storage.manager import enterprise_store, health_report_store
from backend.schemas.enterprise import (
    EnterpriseCreate, EnterpriseUpdate, EnterpriseResponse,
    EnterpriseListResponse, EnterpriseListItem, EnterpriseStatus
)

router = APIRouter(prefix="/api/enterprises", tags=["enterprises"])


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
):
    """List enterprises with pagination, filtering, and sorting."""
    filters = {}
    if search:
        filters["name"] = search  # Simple exact match; ilike handled below
    if status:
        filters["status"] = status
    if source:
        filters["source"] = source

    all_enterprises = enterprise_store.filter(
        order_by=sort_by, order_desc=(sort_order == "desc")
    )

    # Apply search filter (ilike for name)
    if search:
        all_enterprises = [e for e in all_enterprises if search.lower() in e.name.lower()]

    # Apply status/source filters
    if status:
        all_enterprises = [e for e in all_enterprises if e.status == status]
    if source:
        all_enterprises = [e for e in all_enterprises if e.source == source]

    total = len(all_enterprises)

    # Apply pagination
    offset = (page - 1) * page_size
    enterprises = all_enterprises[offset:offset + page_size]

    items = []
    for ent in enterprises:
        report = _get_latest_report(str(ent.id))
        items.append(EnterpriseListItem(
            id=str(ent.id),
            name=ent.name,
            industry=ent.industry,
            financing_score=report.financing_score if report else None,
            last_analysis_date=report.analysis_date if report else None,
            status=EnterpriseStatus(ent.status),
            source=ent.source,
        ))

    return EnterpriseListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.post("", response_model=EnterpriseResponse)
async def create_enterprise(req: EnterpriseCreate):
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
        "channel_id": str(uuid.uuid4()),
    }

    enterprise = enterprise_store.create(**data)
    return EnterpriseResponse(
        id=enterprise.id,
        name=enterprise.name,
        tax_number=enterprise.tax_number,
        taxpayer_type=enterprise.taxpayer_type,
        industry=enterprise.industry,
        province=enterprise.province,
        city=enterprise.city,
        source=enterprise.source,
        status=EnterpriseStatus(enterprise.status),
        channel_id=enterprise.channel_id,
        created_at=enterprise.created_at,
        updated_at=enterprise.updated_at,
    )


@router.get("/{enterprise_id}", response_model=EnterpriseResponse)
async def get_enterprise(enterprise_id: str):
    """Get enterprise details by ID."""
    enterprise = enterprise_store.get_by_id(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    report = _get_latest_report(enterprise_id)

    return EnterpriseResponse(
        id=enterprise.id,
        name=enterprise.name,
        tax_number=enterprise.tax_number,
        taxpayer_type=enterprise.taxpayer_type,
        industry=enterprise.industry,
        province=enterprise.province,
        city=enterprise.city,
        source=enterprise.source,
        status=EnterpriseStatus(enterprise.status),
        channel_id=enterprise.channel_id,
        assigned_operator_id=enterprise.assigned_operator_id,
        created_at=enterprise.created_at,
        updated_at=enterprise.updated_at,
    )


@router.put("/{enterprise_id}", response_model=EnterpriseResponse)
async def update_enterprise(enterprise_id: str, req: EnterpriseUpdate):
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
        id=updated.id,
        name=updated.name,
        tax_number=updated.tax_number,
        taxpayer_type=updated.taxpayer_type,
        industry=updated.industry,
        province=updated.province,
        city=updated.city,
        source=updated.source,
        status=EnterpriseStatus(updated.status),
        channel_id=updated.channel_id,
        assigned_operator_id=updated.assigned_operator_id,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )


@router.delete("/{enterprise_id}")
async def delete_enterprise(enterprise_id: str):
    """Delete an enterprise."""
    enterprise = enterprise_store.get_by_id(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    enterprise_store.delete(enterprise_id)
    return {"message": "Enterprise deleted successfully"}


@router.get("/{enterprise_id}/summary")
async def get_enterprise_summary(enterprise_id: str):
    """Get enterprise summary statistics."""
    enterprise = enterprise_store.get_by_id(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    # Get counts via filter (simplified for JSON store)
    from backend.storage.manager import invoice_store, bank_transaction_store

    invoice_count = len(invoice_store.filter(enterprise_id=enterprise_id))
    tx_count = len(bank_transaction_store.filter(enterprise_id=enterprise_id))
    report = _get_latest_report(enterprise_id)

    return {
        "enterprise_id": enterprise_id,
        "enterprise_name": enterprise.name,
        "invoice_count": invoice_count,
        "transaction_count": tx_count,
        "latest_report_id": report.id if report else None,
        "latest_report_score": report.overall_score if report else None,
        "latest_report_date": report.analysis_date if report else None,
    }