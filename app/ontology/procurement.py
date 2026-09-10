"""Deterministic, whole-group procurement arithmetic; no model defaults."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal("0.01")
TAX_TOLERANCE = CENT
PAYMENT_TOLERANCE = CENT
ENGINE_VERSION = "reconciliation-v2"


def decimal_field(value, *, rate=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("缺少有效数值")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            raise ValueError("数值必须非负且有限")
        if rate:
            if number > 1:
                raise ValueError("税率必须在 0 至 1 之间")
        elif number >= Decimal("1e12") or number != number.quantize(CENT):
            raise ValueError("金额必须精确到分且小于一万亿元")
        return number
    except InvalidOperation as exc:
        raise ValueError("金额格式无效") from exc


def procurement_amounts(facts):
    invoices, payments = [], []
    for fact in facts:
        data = fact["data"]
        kind = data.get("record_type")
        if kind not in {"INVOICE", "PAYMENT"}:
            continue
        row = {"fact_id": fact["object_id"], "version": fact["version"],
               "source_artifact_id": data["source_artifact_id"], "source_anchor": data["source_anchor"], "errors": {}}
        fields = ("invoice_total", "net_amount", "tax", "tax_rate") if kind == "INVOICE" else ("payment_total",)
        for field in fields:
            try:
                row[field] = decimal_field(data.get("normalized_value", {}).get(field), rate=field == "tax_rate")
            except ValueError as exc:
                row[field] = None
                row["errors"][field] = str(exc)
        if kind == "INVOICE":
            if all(row[k] is not None for k in ("invoice_total", "net_amount", "tax")):
                row["total_delta"] = row["invoice_total"] - row["net_amount"] - row["tax"]
            if all(row[k] is not None for k in ("net_amount", "tax", "tax_rate")):
                row["expected_tax"] = (row["net_amount"] * row["tax_rate"]).quantize(CENT, rounding=ROUND_HALF_UP)
                row["tax_delta"] = row["tax"] - row["expected_tax"]
            invoices.append(row)
        else:
            payments.append(row)

    def total(rows, field):
        if not rows or any(r[field] is None for r in rows):
            return None
        return sum((r[field] for r in rows), Decimal("0"))

    gross, paid = total(invoices, "invoice_total"), total(payments, "payment_total")
    net, tax = total(invoices, "net_amount"), total(invoices, "tax")
    return {"invoices": invoices, "payments": payments, "invoice_total": gross, "payment_total": paid,
            "net_amount": net, "tax": tax, "delta": paid - gross if gross is not None and paid is not None else None,
            "invoice_valid": bool(invoices) and all(r.get("total_delta") == 0 and r["invoice_total"] > 0 for r in invoices),
            "tax_valid": bool(invoices) and all(r.get("tax_delta") is not None and abs(r["tax_delta"]) <= TAX_TOLERANCE for r in invoices),
            "balance_delta": net + tax - paid if all(n is not None for n in (net, tax, paid)) else None}
