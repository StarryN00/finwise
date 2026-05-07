"""
Import Router - handles data import for invoices, bank statements, and financial statements.
Supports Excel (.xls, .xlsx), CSV, and PDF formats.
Uses JSONStore for persistence.
"""
import uuid
from datetime import date
from typing import List, Optional
from decimal import Decimal

from fastapi import APIRouter, HTTPException, UploadFile, File, Query

from backend.storage.manager import (
    enterprise_store, import_batch_store, invoice_store, bank_transaction_store
)
from backend.models.schemas import (
    ImportJobResponse, InvoiceImportRequest, InvoiceResponse,
    BankStatementParseRequest, BankStatementParseResponse,
    InvoiceItem
)
from backend.services.file_service import file_service
from backend.services.ai_service import parse_bank_statement_with_ai

router = APIRouter(prefix="/api/import", tags=["import"])

# Status enum simulation
class ImportStatus:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ============ File Upload & Import Jobs ============

@router.post("/invoices", response_model=ImportJobResponse)
async def import_invoices(
    enterprise_id: uuid.UUID,
    file: UploadFile = File(...),
):
    """
    Import invoices from Excel/CSV file.
    Supported formats: .xls, .xlsx, .csv
    """
    # Verify enterprise exists
    enterprise = enterprise_store.get_by_id(dict, str(enterprise_id))
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    # Validate file type
    filename = file.filename or ""
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    if ext not in ("xls", "xlsx", "csv"):
        raise HTTPException(status_code=400, detail="Unsupported file type. Use .xls, .xlsx, or .csv")

    # Save file
    file_id, file_url = await file_service.save_upload(file, subfolder=f"imports/{enterprise_id}")

    # Create import batch
    batch_id = str(uuid.uuid4())
    batch = import_batch_store.create(
        dict,
        id=batch_id,
        enterprise_id=str(enterprise_id),
        import_type="INVOICE",
        file_name=filename,
        total_rows=0,
        processed_rows=0,
        status=ImportStatus.PENDING,
    )

    # Parse the file
    try:
        invoices = await _parse_invoice_file(file, filename)
        batch['total_rows'] = len(invoices)
        batch['processed_rows'] = 0
        batch['status'] = ImportStatus.PROCESSING
        import_batch_store.update(dict, batch_id, **batch)

        # Insert invoices
        for item in invoices:
            invoice_store.create(
                dict,
                id=str(uuid.uuid4()),
                enterprise_id=str(enterprise_id),
                invoice_number=item["invoice_number"],
                invoice_type=item["invoice_type"],
                issue_date=item["issue_date"].isoformat() if isinstance(item["issue_date"], date) else str(item["issue_date"]),
                amount=float(item["amount"]),
                tax_amount=float(item["tax_amount"]),
                total_amount=float(item["total_amount"]),
                seller_name=item["seller_name"],
                seller_tax_number=item["seller_tax_number"],
                buyer_name=item["buyer_name"],
                buyer_tax_number=item["buyer_tax_number"],
                import_batch_id=batch_id,
                status="PENDING",
            )
            batch['processed_rows'] += 1

        batch['status'] = ImportStatus.COMPLETED
        import_batch_store.update(dict, batch_id, **batch)

    except Exception as e:
        import_batch_store.update(dict, batch_id, status=ImportStatus.FAILED, error_message=str(e))

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
):
    """
    Import bank statements from Excel/CSV/PDF.
    For Excel/CSV: directly parse and store.
    For PDF: store file, trigger AI parsing.
    Returns job_id for tracking AI parsing status.
    """
    # Verify enterprise
    enterprise = enterprise_store.get_by_id(dict, str(enterprise_id))
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    filename = file.filename or ""
    ext = filename.lower().split(".")[-1] if "." in filename else ""

    if ext not in ("xls", "xlsx", "csv", "pdf"):
        raise HTTPException(status_code=400, detail="Unsupported file type. Use .xls, .xlsx, .csv, or .pdf")

    # Save file
    file_id, file_url = await file_service.save_upload(file, subfolder=f"bank_statements/{enterprise_id}")

    # Create import batch
    batch_id = str(uuid.uuid4())
    batch = import_batch_store.create(
        dict,
        id=batch_id,
        enterprise_id=str(enterprise_id),
        import_type="BANK_STATEMENT",
        file_name=filename,
        status=ImportStatus.PENDING,
        total_rows=0,
        processed_rows=0,
    )

    if ext in ("xls", "xlsx", "csv"):
        # Direct parse for Excel/CSV
        batch['status'] = ImportStatus.PROCESSING
        import_batch_store.update(dict, batch_id, **batch)
        try:
            raw_text = await _parse_excel_or_csv(file, filename)
            # Store raw text for now - AI parse will happen on confirm
            transactions = await parse_bank_statement_with_ai(
                batch_id, enterprise_id, raw_text
            )
            batch['total_rows'] = len(transactions)
            batch['processed_rows'] = len(transactions)
            batch['status'] = ImportStatus.COMPLETED
            import_batch_store.update(dict, batch_id, **batch)
        except Exception as e:
            import_batch_store.update(dict, batch_id, status=ImportStatus.FAILED, error_message=str(e))
    else:
        # PDF - just store, AI parse triggered separately
        batch['status'] = ImportStatus.PENDING
        batch['total_rows'] = 0
        import_batch_store.update(dict, batch_id, **batch)

    return BankStatementParseResponse(
        job_id=uuid.UUID(batch_id),
        status=batch['status'],
    )


@router.get("/jobs/{job_id}", response_model=ImportJobResponse)
async def get_import_job(job_id: uuid.UUID):
    """Get import job status."""
    batch = import_batch_store.get_by_id(dict, str(job_id))
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

async def _parse_invoice_file(file: UploadFile, filename: str) -> List[dict]:
    """
    Parse invoice Excel/CSV file and return list of invoice dicts.
    This is a simplified parser - in production you'd use openpyxl/pandas.
    """
    import pandas as pd
    from io import BytesIO

    content = await file.read()
    if filename.endswith(".csv"):
        df = pd.read_csv(BytesIO(content))
    else:
        df = pd.read_excel(BytesIO(content))

    # Normalize columns
    df.columns = df.columns.str.strip()

    # Map common column names
    column_map = {
        "发票号码": "invoice_number",
        "发票号": "invoice_number",
        "发票类型": "invoice_type",
        "开票日期": "issue_date",
        "金额": "amount",
        "税额": "tax_amount",
        "价税合计": "total_amount",
        "销售方名称": "seller_name",
        "销售方纳税人识别号": "seller_tax_number",
        "购买方名称": "buyer_name",
        "购买方纳税人识别号": "buyer_tax_number",
    }

    normalized = df.rename(columns=column_map)

    invoices = []
    for _, row in normalized.iterrows():
        # Parse date
        issue_date = row.get("issue_date")
        if isinstance(issue_date, str):
            issue_date = date.fromisoformat(issue_date)
        elif hasattr(issue_date, "date"):
            issue_date = issue_date.date()
        else:
            issue_date = date.today()

        # Normalize invoice type
        inv_type = str(row.get("invoice_type", "VAT_SPECIAL")).upper()
        if "普通" in inv_type:
            inv_type = "VAT_NORMAL"
        else:
            inv_type = "VAT_SPECIAL"

        invoices.append({
            "invoice_number": str(row.get("invoice_number", "")),
            "invoice_type": inv_type,
            "issue_date": issue_date,
            "amount": float(row.get("amount", 0)),
            "tax_amount": float(row.get("tax_amount", 0)),
            "total_amount": float(row.get("total_amount", 0)),
            "seller_name": str(row.get("seller_name", "")),
            "seller_tax_number": str(row.get("seller_tax_number", "")),
            "buyer_name": str(row.get("buyer_name", "")),
            "buyer_tax_number": str(row.get("buyer_tax_number", "")),
        })

    return invoices


async def _parse_excel_or_csv(file: UploadFile, filename: str) -> str:
    """Parse Excel/CSV file and return raw text for AI parsing."""
    import pandas as pd
    from io import BytesIO

    content = await file.read()
    if filename.endswith(".csv"):
        df = pd.read_csv(BytesIO(content))
    else:
        df = pd.read_excel(BytesIO(content))

    # Convert to CSV-like text for AI parsing
    return df.to_csv(index=False, encoding="utf-8-sig")
