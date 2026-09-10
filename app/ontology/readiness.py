"""Read-only, purpose-specific readiness. Never promotes a financial object."""
from collections import Counter

from app.ontology.baseline import previous_period


KINDS = {
    "purchase_invoices": "purchase", "contract": "purchase", "stock_in": "purchase",
    "sales_invoices": "sales", "bank_statement": "bank", "electronic_acceptance": "bank",
    "payroll": "people", "social_security": "people", "housing_fund": "people",
    "individual_income_tax": "people", "opening_balance": "baseline",
}
TYPES = {"INVOICE": "purchase", "CONTRACT": "purchase", "STOCK_IN": "purchase",
         "SALES_INVOICE": "sales", "PAYMENT": "bank", "RECEIPT": "bank",
         "BANK_TRANSACTION": "bank", "ELECTRONIC_ACCEPTANCE": "bank",
         "PAYROLL": "people", "SOCIAL_SECURITY": "people", "HOUSING_FUND": "people",
         "INDIVIDUAL_INCOME_TAX": "people"}
FIELDS = {"tax_rate": "税率", "tax": "税额", "net_amount": "不含税金额", "invoice_total": "价税合计",
          "invoice_status": "发票状态", "invoice_no": "发票号码", "transaction_date": "交易日期",
          "invoice_date": "开票日期", "direction": "收支方向", "expense": "支出金额", "income": "收入金额",
          "balance": "余额", "bank_account_ref": "本方账户", "period": "业务期间"}


def issue_text(value):
    field, sep, reason = str(value).partition("：")
    return f"{FIELDS.get(field, '提取字段')}：{reason}" if sep else str(value)


def build_readiness(scope, *, artifacts, facts, baseline, baseline_valid, checked_groups, checked_vouchers, model_runs):
    categories = {key: {"id": key, "name": name, "artifact_ids": [], "record_ids": [], "issues": []}
                  for key, name in [("baseline", "期初与历史衔接"), ("purchase", "采购及入库"),
                                    ("sales", "销售"), ("bank", "银行与票据"),
                                    ("people", "薪酬及税费"), ("unassigned", "归属或用途待确认")]}
    active = {a["object_id"]: a for a in artifacts if a["status"] != "ARCHIVED"}
    live_facts = [f for f in facts if f["data"].get("source_artifact_id") in active and f["status"] not in {"VOID", "ARCHIVED", "SUPERSEDED"}]
    prior = previous_period(scope.accounting_period_id)
    refs = baseline["data"].get("confirmed_inputs") or {}
    balance_id = (refs.get("balance_source") or {}).get("artifact_id")
    close_id = (refs.get("close_source") or {}).get("artifact_id")
    baseline_sources = {"balance": [], "close": []}
    owners = {}
    for aid, artifact in active.items():
        data = artifact["data"]
        purpose, kind = data.get("source_purpose"), (data.get("parse_options") or {}).get("document_kind")
        if purpose in {"opening_balance", "prior_close", "historical_reference"} or aid in {balance_id, close_id} or kind == "opening_balance":
            category = "baseline"
            if data.get("observed_period") == prior:
                if purpose == "opening_balance" or aid == balance_id or kind == "opening_balance":
                    baseline_sources["balance"].append(aid)
                if purpose == "prior_close" or aid == close_id:
                    baseline_sources["close"].append(aid)
        elif data.get("observed_period") != scope.accounting_period_id:
            category = "unassigned"
        else:
            category = KINDS.get(kind)
            if not category:
                inferred = {TYPES.get(f["data"].get("record_type")) for f in live_facts if f["data"].get("source_artifact_id") == aid}
                category = inferred.pop() if len(inferred) == 1 else None
            category = category or "unassigned"
        categories[category]["artifact_ids"].append(aid)
        owners[aid] = category

    verified = {fid for g in checked_groups for fid in g["data"].get("member_fact_ids", [])}
    records, grouped_issues = [], {}
    for fact in live_facts:
        data, fid = fact["data"], fact["object_id"]
        aid = data["source_artifact_id"]
        artifact, category = active[aid], owners[aid]
        categories[category]["record_ids"].append(fid)
        issues = list(dict.fromkeys(data.get("extraction_issues") or []))
        period_error = data.get("period_check") != "PASS" or fact["status"] == "PERIOD_EXCEPTION"
        if period_error:
            issues.append("period：不属于已核定的本期业务范围，需核对原件与业务日期")
        state = "PERIOD_EXCEPTION" if period_error else "NEEDS_REVIEW" if issues or fact["status"] != "PARSED" else "EXTRACTED"
        # A parser status, a model suggestion and a human read-receipt are not verification.
        if fid in verified and not issues and artifact["status"] == "ACTIVE":
            state = "CHECKED"
        record = {"object_id": fid, "version": fact["version"], "category_id": category,
                  "source_artifact_id": aid, "filename": artifact["data"]["filename"],
                  "source_anchor": data.get("source_anchor"), "record_type": data.get("record_type"),
                  "state": state, "issues": [issue_text(i) for i in issues],
                  "values": data.get("normalized_value") or {}, "field_sources": data.get("field_sources") or {}}
        records.append(record)
        for issue in issues:
            key = (aid, issue)
            if key not in grouped_issues:
                grouped_issues[key] = {"id": f"issue-{len(grouped_issues)+1}", "category_id": category,
                                      "artifact_id": aid, "title": issue_text(issue), "record_ids": []}
            grouped_issues[key]["record_ids"].append(fid)
    for issue in grouped_issues.values():
        issue["record_count"] = len(issue["record_ids"])
        categories[issue["category_id"]]["issues"].append(issue)
    for category in categories.values():
        cat_records = [r for r in records if r["category_id"] == category["id"]]
        category["file_count"] = len(category["artifact_ids"])
        category["record_count"] = len(cat_records)
        category["verified_count"] = sum(r["state"] == "CHECKED" for r in cat_records)
        category["review_count"] = sum(r["state"] in {"NEEDS_REVIEW", "PERIOD_EXCEPTION"} for r in cat_records)
        category["business_issues"] = []
        category["pending_parse_count"] = sum(active[aid]["data"].get("parse_status", "RECEIVED") in {"RECEIVED", "FAILED"} for aid in category["artifact_ids"])

    usable = []
    if baseline_valid:
        usable.append({"kind": "baseline", "object_id": baseline["object_id"], "title": "期初余额已人工核实",
                       "use": "可用于本期账务衔接", "confirmed_by": baseline["data"].get("confirmed_by"),
                       "confirmed_at": baseline["data"].get("decision_time"),
                       "source_ids": list(dict.fromkeys(i for i in [balance_id, close_id] if i)),
                       "version": baseline["version"]})
    for group in checked_groups:
        usable.append({"kind": "group", "object_id": group["object_id"], "version": group["version"],
                       "title": "业务校验通过", "use": "可进入该业务的后续处理；凭证仍须单独复核",
                       "source_ids": group["data"].get("member_fact_ids", []),
                       "confirmed_by": group["data"].get("confirmed_by"),
                       "confirmed_at": group["data"].get("decision_time")})
    for voucher in checked_vouchers:
        usable.append({"kind": "voucher", "object_id": voucher["object_id"], "version": voucher["version"],
                       "title": "凭证已本地复核", "use": "本地复核成果，不代表外部系统已入账",
                       "source_ids": [voucher["data"]["group_id"]],
                       "confirmed_by": voucher["data"].get("validated_by"),
                       "confirmed_at": voucher["data"].get("validated_at")})
    calls, covered = [], set()
    for run in model_runs:
        if run['data'].get('stage') == 'MATERIAL_GUIDANCE':
            continue  # UI guidance does not contribute to business fact coverage.
        data, gateway = run["data"], run["data"].get("gateway") or {}
        inputs = (data.get("input_summary") or {}).get("facts") or []
        real_success = run["status"] == "SUCCEEDED" and gateway.get("mock") is False
        if real_success:
            covered.update(f["fact_id"] for f in inputs if f.get("fact_id"))
        calls.append({"object_id": run["object_id"], "status": run["status"], "real_success": real_success,
                      "mock": gateway.get("mock"), "stage": data.get("stage"), "input_count": len(inputs),
                      "model": data.get("model_version") or gateway.get("model_version"), "created_at": run["created_at"]})
    states = Counter(r["state"] for r in records)
    return {"version": "data-readiness-v1", "categories": list(categories.values()), "records": records,
            "baseline_sources": baseline_sources, "usable_results": usable,
            "counts": {"files": len(active), "records": len(records), "extracted_pending": states["EXTRACTED"],
                       "verified_records": states["CHECKED"], "needs_review": states["NEEDS_REVIEW"],
                       "period_exceptions": states["PERIOD_EXCEPTION"], "issue_types": len(grouped_issues)},
            "model_coverage": {"real_successful_calls": sum(c["real_success"] for c in calls),
                               "historical_fact_count": len(covered), "current_verified_count": 0,
                               "note": "仅表示调用时的输入覆盖，不代表当前版本已核实", "calls": calls}}
