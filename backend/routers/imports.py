"""
Import Router - handles data import for invoices, bank statements, and financial statements.
Supports Excel (.xls, .xlsx), CSV, and PDF formats.
Uses JSONStore for persistence.
"""
import uuid
from datetime import date
from pathlib import Path
from typing import List, Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel

from backend.core.config import settings
from backend.storage.manager import (
    enterprise_store, import_batch_store, invoice_store, bank_transaction_store
)
from backend.routers.auth import get_current_user
from backend.models.schemas import (
    ImportJobResponse, InvoiceImportRequest, InvoiceResponse,
    BankStatementParseRequest, BankStatementParseResponse,
    InvoiceItem
)
from backend.services.file_service import file_service
from backend.services.ai_service import parse_bank_statement_with_ai
from backend.services.statement_import import (
    EnterpriseMetadata,
    extract_enterprise_metadata,
    infer_period_from_filename,
    parse_bank_statement_file,
)
from backend.services.invoice_import import parse_invoice_detail_file

router = APIRouter(prefix="/api/import", tags=["import"])

# Status enum simulation
class ImportStatus:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EnterpriseDirectoryImportRequest(BaseModel):
    directory_path: str = "/Volumes/共享文件夹/财务项目/银行流水"
    taxpayer_type: str = "SMALL"
    source: str = "DIRECT"
    import_bank_statements: bool = True
    import_invoice_details: bool = True


class EnterpriseImportSummary(BaseModel):
    total_files: int = 0
    enterprises_created: int = 0
    enterprises_updated: int = 0
    bank_files_imported: int = 0
    transactions_imported: int = 0
    invoice_files_imported: int = 0
    invoice_rows_imported: int = 0
    client_list_files_imported: int = 0
    skipped_files: int = 0
    errors: list[dict] = []


def _find_or_create_enterprise(metadata, taxpayer_type: str = "SMALL", source: str = "DIRECT") -> tuple[dict, bool]:
    name = metadata.name
    if not name:
        raise ValueError("Missing enterprise name")

    existing = None
    if metadata.tax_number:
        existing = enterprise_store.first(tax_number=metadata.tax_number)
    if not existing:
        existing = enterprise_store.first(name=name)
    if existing:
        updates = {}
        if existing.get("channel_id") != settings.DEFAULT_CHANNEL_ID:
            updates["channel_id"] = settings.DEFAULT_CHANNEL_ID
        if metadata.tax_number and not existing.get("tax_number"):
            updates["tax_number"] = metadata.tax_number
        if metadata.business_scope and not existing.get("business_scope"):
            updates["business_scope"] = metadata.business_scope
        if updates:
            return enterprise_store.update(existing["id"], **updates), False
        return existing, False

    enterprise = enterprise_store.create(
        id=str(uuid.uuid4()),
        name=name,
        tax_number=metadata.tax_number or f"TEMP-{uuid.uuid4().hex[:12].upper()}",
        taxpayer_type=taxpayer_type,
        industry=_infer_industry(metadata.business_scope or name),
        registered_capital_range=None,
        founded_year=None,
        province="江苏",
        city=_infer_city(name),
        source=source,
        assigned_operator_id=None,
        status="ACTIVE",
        channel_id=settings.DEFAULT_CHANNEL_ID,
        business_scope=metadata.business_scope,
    )
    return enterprise, True


def _infer_city(name: str) -> str:
    if name.startswith("苏州"):
        return "苏州"
    if name.startswith("昆山") or name.startswith("昆山市"):
        return "昆山"
    return ""


def _infer_industry(text: str) -> str:
    if any(keyword in text for keyword in ("劳务", "服务", "企业管理")):
        return "服务业"
    if any(keyword in text for keyword in ("制造", "材料", "电子", "高分子", "精密")):
        return "制造业"
    if any(keyword in text for keyword in ("技术", "软件", "智能", "纳米", "科技")):
        return "科技"
    return "其他"


def _import_bank_file_for_enterprise(path: Path, enterprise: dict) -> tuple[int, bool]:
    existing_batch = import_batch_store.first(
        enterprise_id=enterprise["id"],
        import_type="BANK_STATEMENT",
        file_name=path.name,
    )
    if (
        existing_batch
        and existing_batch.get("status") == ImportStatus.COMPLETED
        and int(existing_batch.get("total_rows") or 0) > 0
    ):
        return 0, False

    batch_id = existing_batch["id"] if existing_batch else str(uuid.uuid4())
    if existing_batch:
        for tx in bank_transaction_store.filter(import_batch_id=batch_id):
            bank_transaction_store.delete(tx["id"])

    year, month = infer_period_from_filename(path)
    batch_payload = {
        "enterprise_id": enterprise["id"],
        "import_type": "BANK_STATEMENT",
        "file_name": path.name,
        "source_path": str(path),
        "period_year": year,
        "period_month": month,
        "status": ImportStatus.PROCESSING,
        "total_rows": 0,
        "processed_rows": 0,
    }
    if existing_batch:
        import_batch_store.update(batch_id, **batch_payload)
    else:
        import_batch_store.create(id=batch_id, **batch_payload)

    transactions = parse_bank_statement_file(path, enterprise["id"], batch_id)
    if not transactions:
        import_batch_store.update(
            batch_id,
            total_rows=0,
            processed_rows=0,
            status=ImportStatus.FAILED,
            error_message="未识别到银行流水明细",
        )
        raise ValueError("未识别到银行流水明细")

    created_count = 0
    for tx in transactions:
        if _bank_transaction_exists(tx, batch_id):
            continue
        bank_transaction_store.create(id=str(uuid.uuid4()), **tx)
        created_count += 1

    import_batch_store.update(
        batch_id,
        total_rows=len(transactions),
        processed_rows=created_count,
        status=ImportStatus.COMPLETED,
    )
    return created_count, True


def _bank_transaction_exists(tx: dict, current_batch_id: str) -> bool:
    existing = bank_transaction_store.filter(
        enterprise_id=tx["enterprise_id"],
        transaction_date=tx["transaction_date"],
        summary=tx["summary"],
    )
    for item in existing:
        if item.get("import_batch_id") == current_batch_id:
            continue
        if (
            item.get("debit_amount") == tx.get("debit_amount")
            and item.get("credit_amount") == tx.get("credit_amount")
            and item.get("balance") == tx.get("balance")
            and item.get("status") != "DELETED"
        ):
            return True
    return False


def _is_invoice_detail_file(path: Path) -> bool:
    return any(keyword in path.stem for keyword in ("进项", "销项"))


def _is_client_list_file(path: Path) -> bool:
    return "客户清单" in path.stem or "企业清单" in path.stem


def _import_enterprises_from_client_list(path: Path, taxpayer_type: str, source: str) -> tuple[int, int]:
    import pandas as pd

    df = pd.read_excel(path, dtype=object)
    df.columns = [str(col).strip() for col in df.columns]
    created_count = 0
    updated_count = 0
    for _, row in df.iterrows():
        name = str(row.get("企业名称", "") or "").strip()
        if not name:
            continue
        metadata = EnterpriseMetadata(
            name=name,
            tax_number=str(row.get("纳税人识别号", "") or "").strip() or None,
            business_scope=str(row.get("经营范围", "") or "").strip() or None,
        )
        _, created = _find_or_create_enterprise(metadata, taxpayer_type=taxpayer_type, source=source)
        if created:
            created_count += 1
        else:
            updated_count += 1
    return created_count, updated_count


def _import_invoice_file_for_enterprise(path: Path, enterprise: dict) -> tuple[int, bool]:
    existing_batch = import_batch_store.first(
        enterprise_id=enterprise["id"],
        import_type="INVOICE",
        file_name=path.name,
    )
    if (
        existing_batch
        and existing_batch.get("status") == ImportStatus.COMPLETED
        and int(existing_batch.get("total_rows") or 0) > 0
    ):
        return 0, False

    batch_id = existing_batch["id"] if existing_batch else str(uuid.uuid4())
    if existing_batch:
        for invoice in invoice_store.filter(import_batch_id=batch_id):
            invoice_store.delete(invoice["id"])

    year, month = infer_period_from_filename(path)
    batch_payload = {
        "enterprise_id": enterprise["id"],
        "import_type": "INVOICE",
        "file_name": path.name,
        "source_path": str(path),
        "period_year": year,
        "period_month": month,
        "status": ImportStatus.PROCESSING,
        "total_rows": 0,
        "processed_rows": 0,
    }
    if existing_batch:
        import_batch_store.update(batch_id, **batch_payload)
    else:
        import_batch_store.create(id=batch_id, **batch_payload)

    invoices = parse_invoice_detail_file(path, enterprise)
    if not invoices:
        import_batch_store.update(
            batch_id,
            total_rows=0,
            processed_rows=0,
            status=ImportStatus.FAILED,
            error_message="未识别到进销项明细",
        )
        raise ValueError("未识别到进销项明细")

    for index, item in enumerate(invoices, start=1):
        invoice_store.create(
            id=str(uuid.uuid4()),
            enterprise_id=enterprise["id"],
            invoice_number=item["invoice_number"],
            invoice_type=item["invoice_type"],
            direction=item.get("direction", "UNKNOWN"),
            invoice_kind=item.get("invoice_kind", "UNKNOWN"),
            issue_date=item["issue_date"].isoformat() if isinstance(item["issue_date"], date) else str(item["issue_date"]),
            amount=float(item["amount"]),
            tax_amount=float(item["tax_amount"]),
            total_amount=float(item["total_amount"]),
            seller_name=item["seller_name"],
            seller_tax_number=item["seller_tax_number"],
            buyer_name=item["buyer_name"],
            buyer_tax_number=item["buyer_tax_number"],
            tax_rate=item.get("tax_rate"),
            item_name=item.get("item_name"),
            invoice_status=item.get("invoice_status", "VALID"),
            channel_id=settings.DEFAULT_CHANNEL_ID,
            import_batch_id=batch_id,
            source_row_index=index,
            status="PENDING",
        )

    import_batch_store.update(
        batch_id,
        total_rows=len(invoices),
        processed_rows=len(invoices),
        status=ImportStatus.COMPLETED,
    )
    return len(invoices), True


@router.post("/enterprises/from_directory")
async def import_enterprises_from_directory(
    request: EnterpriseDirectoryImportRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Import enterprise metadata and bank statements from a mounted accountant data directory.
    Expected layout: one enterprise per folder, with Excel/CSV bank statement files inside.
    """
    root = Path(request.directory_path).expanduser().resolve()
    allowed_roots = [
        Path(item).expanduser().resolve()
        for item in settings.IMPORT_DIRECTORY_ALLOWLIST.split(",")
        if item.strip()
    ]
    if not any(root == allowed or allowed in root.parents for allowed in allowed_roots):
        raise HTTPException(status_code=403, detail="Import directory is not allowed")
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=400, detail="Directory not found")

    summary = EnterpriseImportSummary()
    files = sorted([p for p in root.rglob("*") if p.suffix.lower() in {".xls", ".xlsx", ".csv"}])
    summary.total_files = len(files)

    for path in files:
        try:
            if _is_client_list_file(path):
                created_count, updated_count = _import_enterprises_from_client_list(
                    path,
                    taxpayer_type=request.taxpayer_type,
                    source=request.source,
                )
                summary.client_list_files_imported += 1
                summary.enterprises_created += created_count
                summary.enterprises_updated += updated_count
                continue

            metadata = extract_enterprise_metadata(path, fallback_name=path.parent.name)
            enterprise, created = _find_or_create_enterprise(
                metadata,
                taxpayer_type=request.taxpayer_type,
                source=request.source,
            )
            if created:
                summary.enterprises_created += 1
            else:
                summary.enterprises_updated += 1

            if _is_invoice_detail_file(path):
                if request.import_invoice_details:
                    invoice_count, imported = _import_invoice_file_for_enterprise(path, enterprise)
                    if imported:
                        summary.invoice_files_imported += 1
                        summary.invoice_rows_imported += invoice_count
                    else:
                        summary.skipped_files += 1
                else:
                    summary.skipped_files += 1
            elif request.import_bank_statements:
                tx_count, imported = _import_bank_file_for_enterprise(path, enterprise)
                if imported:
                    summary.bank_files_imported += 1
                    summary.transactions_imported += tx_count
                else:
                    summary.skipped_files += 1
        except Exception as exc:
            summary.errors.append({"file": path.name, "error": str(exc)})

    return summary.model_dump()


# ============ File Upload & Import Jobs ============

@router.post("/invoices", response_model=ImportJobResponse)
async def import_invoices(
    enterprise_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Import invoices from Excel/CSV file.
    Supported formats: .xls, .xlsx, .csv
    """
    # Verify enterprise exists
    enterprise = enterprise_store.get_by_id(str(enterprise_id))
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    # Validate file type
    filename = file.filename or ""
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    if ext not in ("xls", "xlsx", "csv"):
        raise HTTPException(status_code=400, detail="Unsupported file type. Use .xls, .xlsx, or .csv")

    # Save file
    file_id, file_url = await file_service.save_upload(file, subfolder=f"imports/{enterprise_id}")

    existing_batch = import_batch_store.first(
        enterprise_id=str(enterprise_id),
        import_type="INVOICE",
        file_name=filename,
    )
    batch_id = existing_batch["id"] if existing_batch else str(uuid.uuid4())
    if existing_batch:
        for invoice in invoice_store.filter(import_batch_id=batch_id):
            invoice_store.delete(invoice["id"])

    batch_payload = dict(
        enterprise_id=str(enterprise_id),
        import_type="INVOICE",
        file_name=filename,
        file_id=str(file_id),
        total_rows=0,
        processed_rows=0,
        status=ImportStatus.PENDING,
    )
    if existing_batch:
        batch = import_batch_store.update(batch_id, **batch_payload)
    else:
        batch = import_batch_store.create(id=batch_id, **batch_payload)

    # Parse the file — read from the saved file on disk, not the consumed UploadFile stream
    try:
        file_path = _get_saved_file_path(file_id, filename, subfolder=f"imports/{enterprise_id}")
        invoices = parse_invoice_detail_file(file_path, enterprise)
        if not invoices:
            raise ValueError("未识别到进销项明细")
        batch['total_rows'] = len(invoices)
        batch['processed_rows'] = 0
        batch['status'] = ImportStatus.PROCESSING
        import_batch_store.update(batch_id, **batch)

        # Insert invoices
        for item in invoices:
            existing_invoice = invoice_store.first(
                enterprise_id=str(enterprise_id),
                invoice_number=item["invoice_number"],
            )
            if existing_invoice and existing_invoice.get("import_batch_id") != batch_id:
                invoice_store.delete(existing_invoice["id"])
            invoice_store.create(
                id=str(uuid.uuid4()),
                enterprise_id=str(enterprise_id),
                invoice_number=item["invoice_number"],
                invoice_type=item["invoice_type"],
                direction=item.get("direction", "UNKNOWN"),
                invoice_kind=item.get("invoice_kind", "UNKNOWN"),
                issue_date=item["issue_date"].isoformat() if isinstance(item["issue_date"], date) else str(item["issue_date"]),
                amount=float(item["amount"]),
                tax_amount=float(item["tax_amount"]),
                total_amount=float(item["total_amount"]),
                seller_name=item["seller_name"],
                seller_tax_number=item["seller_tax_number"],
                buyer_name=item["buyer_name"],
                buyer_tax_number=item["buyer_tax_number"],
                tax_rate=item.get("tax_rate"),
                item_name=item.get("item_name"),
                invoice_status=item.get("invoice_status", "VALID"),
                channel_id=settings.DEFAULT_CHANNEL_ID,
                import_batch_id=batch_id,
                status="PENDING",
            )
            batch['processed_rows'] += 1

        batch['status'] = ImportStatus.COMPLETED
        import_batch_store.update(batch_id, **batch)

    except Exception as e:
        batch = import_batch_store.update(batch_id, status=ImportStatus.FAILED, error_message=str(e))

    return ImportJobResponse(
        id=uuid.UUID(batch['id']),
        enterprise_id=uuid.UUID(batch['enterprise_id']),
        import_type="INVOICE",
        file_name=batch['file_name'],
        total_rows=batch['total_rows'],
        processed_rows=batch['processed_rows'],
        status=batch['status'],
        error_message=batch.get('error_message'),
        created_at=batch['created_at'],
    )


@router.post("/bank_statements", response_model=BankStatementParseResponse)
async def import_bank_statements(
    enterprise_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Import bank statements from Excel/CSV/PDF.
    For Excel/CSV: directly parse and store.
    For PDF: store file, trigger AI parsing.
    Returns job_id for tracking AI parsing status.
    """
    # Verify enterprise
    enterprise = enterprise_store.get_by_id(str(enterprise_id))
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    filename = file.filename or ""
    ext = filename.lower().split(".")[-1] if "." in filename else ""

    if ext not in ("xls", "xlsx", "csv", "pdf"):
        raise HTTPException(status_code=400, detail="Unsupported file type. Use .xls, .xlsx, .csv, or .pdf")

    # Save file
    file_id, file_url = await file_service.save_upload(file, subfolder=f"bank_statements/{enterprise_id}")

    existing_batch = import_batch_store.first(
        enterprise_id=str(enterprise_id),
        import_type="BANK_STATEMENT",
        file_name=filename,
    )
    batch_id = existing_batch["id"] if existing_batch else str(uuid.uuid4())
    if existing_batch:
        for tx in bank_transaction_store.filter(import_batch_id=batch_id):
            bank_transaction_store.delete(tx["id"])

    batch_payload = dict(
        enterprise_id=str(enterprise_id),
        import_type="BANK_STATEMENT",
        file_name=filename,
        file_id=str(file_id),
        status=ImportStatus.PENDING,
        total_rows=0,
        processed_rows=0,
    )
    if existing_batch:
        batch = import_batch_store.update(batch_id, **batch_payload)
    else:
        batch = import_batch_store.create(id=batch_id, **batch_payload)

    if ext in ("xls", "xlsx", "csv"):
        # Direct parse for Excel/CSV
        batch['status'] = ImportStatus.PROCESSING
        import_batch_store.update(batch_id, **batch)
        try:
            file_path = _get_saved_file_path(file_id, filename, subfolder=f"bank_statements/{enterprise_id}")
            transactions = parse_bank_statement_file(file_path, str(enterprise_id), batch_id)
            if not transactions:
                raise ValueError("未识别到银行流水明细")
            for tx in transactions:
                bank_transaction_store.create(id=str(uuid.uuid4()), **tx)
            batch['total_rows'] = len(transactions)
            batch['processed_rows'] = len(transactions)
            batch['status'] = ImportStatus.COMPLETED
            import_batch_store.update(batch_id, **batch)
        except Exception as e:
            import_batch_store.update(batch_id, status=ImportStatus.FAILED, error_message=str(e))
    else:
        # PDF - just store, AI parse triggered separately
        batch['status'] = ImportStatus.PENDING
        batch['total_rows'] = 0
        import_batch_store.update(batch_id, **batch)

    return BankStatementParseResponse(
        job_id=uuid.UUID(batch_id),
        status=batch['status'],
    )


@router.get("/jobs/{job_id}", response_model=ImportJobResponse)
async def get_import_job(
    job_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    """Get import job status."""
    batch = import_batch_store.get_by_id(str(job_id))
    if not batch:
        raise HTTPException(status_code=404, detail="Import job not found")

    return ImportJobResponse(
        id=uuid.UUID(batch['id']),
        enterprise_id=uuid.UUID(batch['enterprise_id']),
        import_type=batch['import_type'],
        file_name=batch['file_name'],
        total_rows=batch['total_rows'],
        processed_rows=batch['processed_rows'],
        status=batch['status'],
        error_message=batch.get('error_message'),
        created_at=batch['created_at'],
    )


# ============ Helper Functions ============

def _get_saved_file_path(file_id: uuid.UUID, filename: str, subfolder: str) -> Path:
    """Get path to a saved file by file_id, original filename, and subfolder."""
    ext = Path(filename).suffix.lower()
    # The file is saved as {file_id}{ext} under the subfolder
    from backend.core.config import settings
    folder = settings.FILES_DIR / subfolder
    return folder / f"{file_id}{ext}"
