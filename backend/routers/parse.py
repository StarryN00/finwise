"""
Parse Router - handles AI parsing of bank statements and transaction-invoice matching.
All AI parsing results require human confirmation before storage.
Uses JSONStore for persistence.
"""
import uuid as uuid_lib
from datetime import date, timedelta
from typing import List, Optional
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query

from backend.storage.manager import (
    enterprise_store, import_batch_store, invoice_store, bank_transaction_store
)
from backend.models.schemas import (
    BankStatementParseRequest, BankStatementParseResponse,
    BankStatementConfirmRequest, TransactionConfirmItem,
    BankStatementPreviewResponse, ParsedTransaction,
    MatchRequest, MatchResponse, MatchCandidate,
    MatchConfirmRequest, MatchConfirmItem
)
from backend.services.ai_service import (
    parse_bank_statement_with_ai,
    match_transactions_with_ai
)

router = APIRouter(prefix="/api/parse", tags=["parse"])

# Status enum simulation
class ImportStatus:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ============ Bank Statement Parsing ============

@router.post("/bank_statement", response_model=BankStatementParseResponse)
async def parse_bank_statement(req: BankStatementParseRequest):
    """
    Trigger AI parsing of a previously uploaded bank statement file.
    Returns job_id for tracking. Results stored as PENDING for human confirmation.
    """
    # Verify enterprise
    enterprise = enterprise_store.get_by_id(str(req.enterprise_id))
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    # Get import batch
    batch = import_batch_store.get_by_id(str(req.file_id))
    if not batch or batch.get('enterprise_id') != str(req.enterprise_id):
        raise HTTPException(status_code=404, detail="Import batch not found")

    # Check if already processed
    if batch.get('status') == ImportStatus.COMPLETED:
        return BankStatementParseResponse(job_id=req.file_id, status="COMPLETED")

    # Mark as processing
    import_batch_store.update(str(req.file_id), status=ImportStatus.PROCESSING)
    batch = import_batch_store.get_by_id(str(req.file_id))

    try:
        # Read file and parse with AI
        raw_text = await _read_import_file(batch['id'], batch['file_name'])
        transactions = await parse_bank_statement_with_ai(
            str(req.file_id), req.enterprise_id, raw_text
        )

        batch['total_rows'] = len(transactions)
        batch['processed_rows'] = len(transactions)
        batch['status'] = ImportStatus.COMPLETED

        # Store parsed transactions as PENDING (awaiting confirmation)
        for tx_data in transactions:
            bank_transaction_store.create(
                id=str(uuid_lib.uuid4()),
                enterprise_id=str(req.enterprise_id),
                transaction_date=tx_data.get("transaction_date", date.today().isoformat()),
                summary=tx_data.get("summary", ""),
                debit_amount=float(tx_data["debit_amount"]) if tx_data.get("debit_amount") else None,
                credit_amount=float(tx_data["credit_amount"]) if tx_data.get("credit_amount") else None,
                balance=float(tx_data["balance"]) if tx_data.get("balance") else None,
                confidence=tx_data.get("confidence"),
                status="PENDING",
                import_batch_id=str(req.file_id),
            )

        import_batch_store.update(str(req.file_id), **batch)

    except Exception as e:
        import_batch_store.update(str(req.file_id), status=ImportStatus.FAILED, error_message=str(e))

    return BankStatementParseResponse(job_id=req.file_id, status=ImportStatus.COMPLETED)


@router.post("/bank_statement/confirm", response_model=dict)
async def confirm_bank_statement(req: BankStatementConfirmRequest):
    """
    Confirm AI-parsed bank statement transactions.
    User can edit/delete rows before confirming.
    """
    # Verify enterprise
    enterprise = enterprise_store.get_by_id(str(req.enterprise_id))
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    # Get existing pending transactions for this batch
    existing_txs = bank_transaction_store.filter(
        import_batch_id=str(req.import_batch_id),
        enterprise_id=str(req.enterprise_id)
    )
    existing_txs_dict = {i: tx for i, tx in enumerate(existing_txs)}
    confirmed_count = 0
    deleted_count = 0

    for item in req.transactions:
        if item.status == "DELETED":
            if item.row_index in existing_txs_dict:
                tx_to_delete = existing_txs_dict[item.row_index]
                bank_transaction_store.delete(tx_to_delete['id'])
                deleted_count += 1
        else:  # CONFIRMED
            confirmed_count += 1

    # Mark all pending as confirmed
    for tx in existing_txs:
        bank_transaction_store.update(tx['id'], status="CONFIRMED")

    return {
        "confirmed": confirmed_count,
        "deleted": deleted_count,
        "message": f"已确认 {confirmed_count} 条，删除 {deleted_count} 条"
    }


@router.get("/bank_statement/preview/{batch_id}", response_model=BankStatementPreviewResponse)
async def preview_bank_statement(batch_id: uuid_lib.UUID, enterprise_id: uuid_lib.UUID):
    """
    Get parsed bank statement preview (before confirmation).
    """
    batch = import_batch_store.get_by_id(str(batch_id))
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")

    transactions = bank_transaction_store.filter(
        import_batch_id=str(batch_id),
        enterprise_id=str(enterprise_id),
    )

    parsed = [
        ParsedTransaction(
            row_index=i,
            transaction_date=tx.get('transaction_date', ''),
            summary=tx.get('summary', ''),
            debit_amount=float(tx['debit_amount']) if tx.get('debit_amount') else None,
            credit_amount=float(tx['credit_amount']) if tx.get('credit_amount') else None,
            balance=float(tx['balance']) if tx.get('balance') else None,
            confidence=tx.get('confidence') or 0.0,
        )
        for i, tx in enumerate(transactions)
    ]

    return BankStatementPreviewResponse(
        job_id=batch_id,
        enterprise_id=enterprise_id,
        status=batch.get('status', 'UNKNOWN'),
        transactions=parsed,
        total_rows=len(parsed),
        ai_model="MiniMax-Text-01",
    )


# ============ Transaction-Invoice Matching ============

@router.post("/match", response_model=MatchResponse)
async def match_transactions(req: MatchRequest):
    """
    Run 3-layer matching between bank transactions and invoices:
    1. Exact: amount + date within 3 days
    2. Fuzzy: amount + date within 7 days
    3. AI: summary keyword + pattern analysis

    Returns candidates sorted by confidence for user confirmation.
    """
    # Verify enterprise
    enterprise = enterprise_store.get_by_id(str(req.enterprise_id))
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    # Get confirmed bank transactions
    transactions = bank_transaction_store.filter(
        enterprise_id=str(req.enterprise_id),
        status="CONFIRMED",
    )

    # Get pending invoices
    invoices = invoice_store.filter(
        enterprise_id=str(req.enterprise_id),
        status="PENDING",
    )

    if not transactions:
        raise HTTPException(status_code=400, detail="No confirmed bank transactions to match")
    if not invoices:
        raise HTTPException(status_code=400, detail="No pending invoices to match")

    # Prepare data for AI
    tx_data = [
        {
            "id": str(tx['id']),
            "transaction_date": tx.get('transaction_date', ''),
            "summary": tx.get('summary', ''),
            "debit_amount": float(tx['debit_amount']) if tx.get('debit_amount') else None,
            "credit_amount": float(tx['credit_amount']) if tx.get('credit_amount') else None,
        }
        for tx in transactions
    ]

    inv_data = [
        {
            "id": str(inv['id']),
            "invoice_number": inv.get('invoice_number', ''),
            "issue_date": inv.get('issue_date', ''),
            "total_amount": float(inv.get('total_amount', 0)),
            "tax_amount": float(inv.get('tax_amount', 0)),
            "seller_name": inv.get('seller_name', ''),
        }
        for inv in invoices
    ]

    # Run 3-layer matching
    match_result = await match_transactions_with_ai(
        str(req.enterprise_id), uuid_lib.uuid4(), tx_data, inv_data
    )

    # Build response
    candidates = []
    matched_tx_indices = set()
    matched_inv_indices = set()

    for cand in match_result.get("candidates", []):
        tx_idx = cand.get("transaction_index")
        inv_idx = cand.get("invoice_index")

        if tx_idx is not None and inv_idx is not None:
            candidates.append(MatchCandidate(
                transaction_index=tx_idx,
                invoice_index=inv_idx,
                confidence=cand.get("confidence", 0.0),
                match_reason=cand.get("match_reason", ""),
            ))
            matched_tx_indices.add(tx_idx)
            matched_inv_indices.add(inv_idx)

    unmatched_txs = [i for i in range(len(transactions)) if i not in matched_tx_indices]
    unmatched_invs = [i for i in range(len(invoices)) if i not in matched_inv_indices]

    return MatchResponse(
        enterprise_id=req.enterprise_id,
        job_id=uuid_lib.uuid4(),
        status="COMPLETED",
        candidates=candidates,
        unmatched_transactions=unmatched_txs,
        unmatched_invoices=unmatched_invs,
    )


@router.post("/match/confirm", response_model=dict)
async def confirm_matches(req: MatchConfirmRequest):
    """
    Confirm transaction-invoice matches.
    User can accept, reject, or modify match pairs.
    """
    # Verify enterprise
    enterprise = enterprise_store.get_by_id(str(req.enterprise_id))
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    updated = 0
    for match in req.matches:
        # Get transaction
        tx = bank_transaction_store.get_by_id(str(match.transaction_id))
        if not tx:
            continue

        if match.invoice_id:
            # Link transaction to invoice
            tx['matched_invoice_id'] = str(match.invoice_id)
            tx['status'] = "CONFIRMED"
            bank_transaction_store.update(str(match.transaction_id), **tx)

            # Update invoice status
            inv = invoice_store.get_by_id(str(match.invoice_id))
            if inv:
                invoice_store.update(str(match.invoice_id), status="MATCHED")
        else:
            # Unmatch
            if tx.get('matched_invoice_id'):
                old_inv_id = tx['matched_invoice_id']
                tx['matched_invoice_id'] = None
                bank_transaction_store.update(str(match.transaction_id), **tx)

                # Restore invoice status
                inv = invoice_store.get_by_id(old_inv_id)
                if inv:
                    invoice_store.update(old_inv_id, status="PENDING")

        updated += 1

    return {"updated": updated, "message": f"已更新 {updated} 条匹配关系"}


# ============ Helper Functions ============

async def _read_import_file(batch_id: str, filename: str) -> str:
    """
    Read the raw content of an imported file for AI parsing.
    For now, returns placeholder - actual implementation needs file storage.
    """
    # In a full implementation, you would read from file storage
    # For now, return empty string to be replaced
    return ""