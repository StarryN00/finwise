from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.enterprise import EnterpriseCreate, EnterpriseRead, InitialSnapshotCreate, InitialSnapshotRead
from app.schemas.monthly import MonthlyPackageCreate, MonthlyPackageRead
from app.services.enterprise_service import (
    ConflictError,
    NotFoundError,
    ValidationError,
    create_enterprise,
    create_monthly_work_package,
    save_initial_snapshot,
)


router = APIRouter(prefix="/api/enterprises", tags=["enterprises"])


@router.post("", response_model=EnterpriseRead, status_code=status.HTTP_201_CREATED)
def create_enterprise_endpoint(payload: EnterpriseCreate, db: Session = Depends(get_db)):
    return _handle_service_errors(
        lambda: create_enterprise(
            db,
            name=payload.name,
            unified_social_credit_code=payload.unified_social_credit_code,
            taxpayer_type=payload.taxpayer_type,
            industry=payload.industry,
            province=payload.province,
            city=payload.city,
        )
    )


@router.post(
    "/{enterprise_id}/initial-snapshot",
    response_model=InitialSnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
def save_initial_snapshot_endpoint(
    enterprise_id: UUID,
    payload: InitialSnapshotCreate,
    db: Session = Depends(get_db),
):
    return _handle_service_errors(
        lambda: save_initial_snapshot(
            db,
            enterprise_id=enterprise_id,
            balance_sheet_data=payload.balance_sheet_data,
            income_statement_data=payload.income_statement_data,
        )
    )


@router.post(
    "/{enterprise_id}/monthly-packages",
    response_model=MonthlyPackageRead,
    status_code=status.HTTP_201_CREATED,
)
def create_monthly_work_package_endpoint(
    enterprise_id: UUID,
    payload: MonthlyPackageCreate,
    db: Session = Depends(get_db),
):
    return _handle_service_errors(
        lambda: create_monthly_work_package(
            db,
            enterprise_id=enterprise_id,
            year=payload.period_year,
            month=payload.period_month,
        )
    )


def _handle_service_errors(action: Callable[[], object]):
    try:
        return action()
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
