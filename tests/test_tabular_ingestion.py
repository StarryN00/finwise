import base64
import hashlib
from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from app.ontology.contracts import ArtifactInput, Scope
from app.ontology.errors import DomainError
from conftest import command


def xlsx_fixture(sheets, dimension="A1:A1"):
    """Small OOXML wire fixture; deliberately reproduces incorrect used-range metadata."""
    out = BytesIO()
    with ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets)+1)) + '</Types>')
        z.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1)) + '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets)+1)) + '</Relationships>')
        for i, (_, rows) in enumerate(sheets, 1):
            xml_rows = []
            for r, row in enumerate(rows, 1):
                cells = []
                for c, value in enumerate(row):
                    ref = chr(65+c) + str(r)
                    if isinstance(value, (int, float)):
                        cells.append(f'<c r="{ref}" t="n"><v>{value}</v></c>')
                    elif value is not None:
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
                xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
            z.writestr(f"xl/worksheets/sheet{i}.xml", f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="{dimension}"/><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    return out.getvalue()


INVOICE_HEADERS = ["发票号码", "开票日期", "金额", "税额", "税率", "销售方纳税人名称"]
INVOICE_ROWS = [INVOICE_HEADERS, ["INV-001", "2026-03-08", "100.00", "13.00", "13%", "合成供应商"],
                ["INV-OLD", "2026-02-28", "200.00", "26.00", "13%", "合成供应商"]]


def uploaded(client, scope, content, filename="发票.xlsx", observed=None):
    service, typed = client.app.state.service, Scope(**scope)
    service.create_scope(typed, actor_id="fixture")
    return service.create_artifact(ArtifactInput(scope=typed, filename=filename,
        content_base64=base64.b64encode(content).decode(), observed_period=observed or typed.accounting_period_id), actor_id="fixture")


def parse(client, scope, source, kind="purchase_invoices", key="parse-original-sheet", **options):
    return command(client, scope, "parse_artifact", source["object_id"], source["version"], key,
                   {"document_kind": kind, **options})


def test_parse_original_xlsx_tracks_cells_and_cross_period_rows(client, scope):
    content = xlsx_fixture([("发票清单", INVOICE_ROWS)])
    source = uploaded(client, scope, content)
    response = parse(client, scope, source)
    assert response.status_code == 200, response.text
    result = response.json()["effect"]
    assert result["artifact"]["data"]["parse_status"] == "PARSED_WITH_ISSUES"
    assert result["counts"] == {"rows": 2, "parsed": 1, "needs_review": 0, "period_exception": 1}
    good, old = result["facts"]
    assert good["status"] == "PARSED" and old["status"] == "PERIOD_EXCEPTION"
    assert good["data"]["normalized_value"]["invoice_total"] == "113.00"
    assert good["data"]["normalized_value"]["tax_rate"] == "0.13"
    assert good["data"]["source_anchor"] == {"row": 2, "region": "发票清单!A2:F2"}
    assert good["data"]["field_sources"]["tax"]["region"] == "发票清单!D2"
    assert good["data"]["original_value"]["values"][0] == "INV-001"
    assert client.app.state.service.store.list_objects("VoucherVersion", Scope(**scope)) == []
    path = client.app.state.settings.storage_path / source["data"]["storage_path"]
    assert path.read_bytes() == content
    assert result["artifact"]["data"]["sha256"] == hashlib.sha256(content).hexdigest()
    response = client.post("/api/v1/business/procurement", json={"scope": scope, "fact_ids": [old["object_id"]], "business_identity": "wrong-month"})
    assert response.status_code == 409


def test_missing_tax_rate_is_not_invented_and_invalid_amount_is_not_zero(client, scope):
    rows = [INVOICE_HEADERS, ["I-1", "2026-03-08", "100.00", "13.00", None, "供应商"],
            ["I-2", "2026-03-09", "not money", "13.00", "13%", "供应商"]]
    source = uploaded(client, scope, xlsx_fixture([("清单", rows)]))
    response = parse(client, scope, source)
    assert response.status_code == 200, response.text
    facts = response.json()["effect"]["facts"]
    assert facts[0]["status"] == "PARSED"
    assert facts[1]["status"] == "NEEDS_REVIEW"
    assert facts[0]["data"]["normalized_value"]["tax_rate"] is None
    assert facts[1]["data"]["normalized_value"]["net_amount"] is None
    assert facts[1]["data"]["normalized_value"]["invoice_total"] is None
    assert facts[0]["data"]["extraction_issues"] == []
    assert facts[0]["data"]["normalized_value"]["tax"] == "13.00"
    assert facts[0]["data"]["field_sources"]["tax_rate"]["status"] == "MISSING"


def test_invoice_header_sheet_is_not_added_to_line_item_summary(client, scope):
    content = xlsx_fixture([("信息汇总表", INVOICE_ROWS * 2), ("发票基础信息", INVOICE_ROWS)])
    source = uploaded(client, scope, content)
    result = parse(client, scope, source, kind="sales_invoices").json()["effect"]
    assert len(result["facts"]) == 2
    assert all(f["data"]["record_type"] == "SALES_INVOICE" for f in result["facts"])
    assert any(s["sheet"] == "信息汇总表" and s["status"] == "REFERENCE_ONLY" for s in result["sheets"])


def test_bank_income_and_expense_have_separate_directions(client, scope):
    rows = [["交易时间", "支出金额", "收入金额", "对方户名", "交易流水号", "摘要"],
            ["2026-03-01 10:25:00", "100.50", "0", "供应商", "000123", "付款"],
            ["2026-03-02", "0", "120.00", "客户", "000124", "收款"]]
    source = uploaded(client, scope, xlsx_fixture([("流水", rows)]))
    response = parse(client, scope, source, kind="bank_statement", bank_account_ref="synthetic-account-a")
    assert response.status_code == 200, response.text
    out, incoming = response.json()["effect"]["facts"]
    assert out["data"]["record_type"] == "PAYMENT" and incoming["data"]["record_type"] == "RECEIPT"
    assert out["data"]["normalized_value"]["transaction_id"] == "000123"
    assert out["data"]["normalized_value"]["payment_total"] == "100.50"
    assert incoming["data"]["normalized_value"]["receipt_total"] == "120.00"


def test_invalid_bank_amount_is_not_coerced_to_zero(client, scope):
    rows = [["交易时间", "支出金额", "收入金额", "对方户名"],
            ["2026-03-01", "not money", "", "供应商"]]
    source = uploaded(client, scope, xlsx_fixture([("流水", rows)]))
    result = parse(client, scope, source, kind="bank_statement", bank_account_ref="synthetic-account-a").json()["effect"]
    fact = result["facts"][0]
    assert fact["status"] == "NEEDS_REVIEW"
    assert fact["data"]["normalized_value"]["expense"] is None
    assert fact["data"]["normalized_value"]["income"] == "0.00"


def test_parse_retry_reuses_facts_and_does_not_rewrite_original(client, scope):
    source = uploaded(client, scope, xlsx_fixture([("清单", INVOICE_ROWS)]))
    first = parse(client, scope, source).json()["effect"]
    same = parse(client, scope, source).json()
    assert same["idempotent"] is True
    again = parse(client, scope, first["artifact"], key="parse-original-again").json()["effect"]
    assert again["facts"] == first["facts"]
    assert again["artifact"] == first["artifact"]


def test_parse_retry_with_different_document_kind_is_rejected(client, scope):
    source = uploaded(client, scope, xlsx_fixture([("清单", INVOICE_ROWS)]))
    assert parse(client, scope, source).status_code == 200
    response = parse(client, scope, source, kind="bank_statement", key="parse-different-kind")
    assert response.status_code == 409, response.text


def test_upload_rejects_oversized_original_before_storage(client, scope):
    service, typed = client.app.state.service, Scope(**scope)
    service.create_scope(typed, actor_id="fixture")
    with pytest.raises(DomainError) as exc_info:
        service.create_artifact(ArtifactInput(scope=typed, filename="too-large.bin", content_base64=base64.b64encode(b"x" * (16 * 1024 * 1024 + 1)).decode()), actor_id="fixture")
    assert getattr(exc_info.value, "code", None) == "ARTIFACT_TOO_LARGE"
    assert service.store.list_objects("SourceArtifact", typed) == []


@pytest.mark.parametrize("problem", ["archived", "tampered", "foreign_scope", "viewer", "unknown_kind", "injected_results", "locked"])
def test_parse_command_rejects_invalid_source_or_authority(client, scope, problem):
    source = uploaded(client, scope, xlsx_fixture([("清单", INVOICE_ROWS)]))
    service, typed = client.app.state.service, Scope(**scope)
    options = {"document_kind": "purchase_invoices"}
    if problem == "archived":
        source = service.archive_artifact(typed, artifact_id=source["object_id"], expected_version=source["version"], actor_id="fixture")
    if problem == "tampered":
        (client.app.state.settings.storage_path / source["data"]["storage_path"]).write_bytes(b"tampered synthetic source")
    if problem == "foreign_scope":
        scope = {**scope, "legal_entity_id": "foreign"}
    if problem == "unknown_kind":
        options["document_kind"] = "auto-confirm-all"
    if problem == "injected_results":
        options["normalized_value"] = {"invoice_total": "1.00"}
    if problem == "locked":
        period = service.workbench(typed)["period"]
        service.store.revise_object(period["object_id"], period["version"], typed, period["data"], status="LOCKED", created_by="fixture")
    response = command(client, scope, "parse_artifact", source["object_id"], source["version"], "invalid-parse-command", options,
                       role="viewer" if problem == "viewer" else "accountant")
    assert response.status_code in {403, 409, 422}, response.text
    assert service.store.list_objects("FactRecord", typed) == []


def test_unrecognized_document_is_recorded_as_failed_without_success_or_facts(client, scope):
    source = uploaded(client, scope, b"not a workbook", filename="broken.xlsx")
    response = parse(client, scope, source)
    assert response.status_code == 200, response.text
    result = response.json()["effect"]
    assert result["artifact"]["data"]["parse_status"] == "FAILED"
    assert result["facts"] == [] and result["errors"]


def test_corrupt_xls_is_recorded_as_failed_without_500_or_facts(client, scope):
    source = uploaded(client, scope, bytes.fromhex("d0cf11e0a1b11ae1") + b"corrupt ole payload", filename="broken.xls")
    response = parse(client, scope, source)
    assert response.status_code == 200, response.text
    result = response.json()["effect"]
    assert result["artifact"]["data"]["parse_status"] == "FAILED"
    assert result["facts"] == [] and result["errors"]


def test_direct_fact_endpoint_cannot_inject_a_new_fact(client, scope):
    source = uploaded(client, scope, xlsx_fixture([("未解析", INVOICE_ROWS)]))
    response = client.post("/api/v1/facts", json={
        "scope": scope, "source_artifact_id": source["object_id"], "source_anchor": {"page": 1},
        "record_type": "INVOICE", "original_value": {}, "normalized_value": {"invoice_total": "999.99"},
        "parser_version": "client-injected", "extraction_confidence": .9,
    })
    assert response.status_code == 403, response.text


def test_generic_juxianda_document_kinds_extract_structured_facts(client, scope):
    fixtures = [
        ("payroll", "工资.xls", [["月份:2026.3月工资条"], ["姓名", "基本工资", "实发工资"], ["员工A", "5000", "4800"]], "PAYROLL", {"person_name": "员工A", "actual_salary": "4800.00"}),
        ("social_security", "社保.xlsx", [["个人编号", "姓名", "对应费款所属期", "险种类型", "单位缴费金额", "个人缴费金额"], ["001", "员工A", "2026-03", "养老", "1000", "500"]], "SOCIAL_SECURITY", {"person_name": "员工A", "period": "2026-03"}),
        ("housing_fund", "公积金.xls", [["个人公积金账号", "姓名", "业务类别", "缴存金额", "入账日期"], ["001", "员工A", "缴存", "500", "2026-03-15"]], "HOUSING_FUND", {"person_name": "员工A", "amount": "500.00"}),
        ("electronic_acceptance", "承兑.xls", [["电子票据号", "票面金额", "交易时间"], ["票据001", "1200", "2026-03-20"]], "ELECTRONIC_ACCEPTANCE", {"acceptance_no": "票据001", "amount": "1200.00"}),
        ("individual_income_tax", "个税.xls", [["申报期：2026年03月"], ["序号", "姓名", "身份证件号码", "所得项目", "", "", "", "收入"], ["1", "员工A", "320000000000000000", "正常工资薪金", "", "", "", "5000"]], "INDIVIDUAL_INCOME_TAX", {"person_name": "员工A", "income": "5000.00"}),
        ("contract", "合同.xlsx", [["合同编号", "合同日期", "供应商名称", "合同金额"], ["HT-001", "2026-03-05", "供应商A", "1130"]], "CONTRACT", {"contract_no": "HT-001", "period": "2026-03"}),
        ("stock_in", "入库.xlsx", [["入库单号", "入库日期", "供应商名称", "入库金额", "存货名称"], ["RK-001", "2026-03-06", "供应商A", "1130", "模具配件"]], "STOCK_IN", {"stock_in_no": "RK-001", "period": "2026-03"}),
    ]
    service, typed = client.app.state.service, Scope(**scope)
    service.create_scope(typed, actor_id="fixture")
    for kind, filename, rows, record_type, expected in fixtures:
        source = service.create_artifact(ArtifactInput(scope=typed, filename=filename,
            content_base64=base64.b64encode(xlsx_fixture([("资料", rows)])).decode(), observed_period="2026-03"), actor_id="fixture")
        response = parse(client, scope, source, kind=kind, key="parse-generic-" + kind)
        assert response.status_code == 200, response.text
        effect = response.json()["effect"]
        assert effect["counts"] == {"rows": 1, "parsed": 1, "needs_review": 0, "period_exception": 0}
        fact = effect["facts"][0]
        assert fact["data"]["record_type"] == record_type
        for field, value in expected.items():
            assert fact["data"]["normalized_value"][field] == value


def test_contract_and_stock_in_facts_complete_procurement_evidence_gate(client, scope):
    invoice = uploaded(client, scope, xlsx_fixture([("清单", INVOICE_ROWS)]), filename="进项.xlsx")
    invoice_result = parse(client, scope, invoice, key="parse-procurement-invoice").json()["effect"]
    invoice_fact = next(item for item in invoice_result["facts"] if item["status"] == "PARSED")
    payment_rows = [["交易时间", "支出金额", "收入金额", "对方户名"], ["2026-03-08", "113.00", "0", "供应商A"]]
    payment = uploaded(client, scope, xlsx_fixture([("流水", payment_rows)]), filename="付款.xlsx")
    payment_result = parse(client, scope, payment, kind="bank_statement", key="parse-procurement-payment").json()["effect"]
    candidate = client.app.state.service.bank_accounts.view(Scope(**scope))['statements'][0]
    response = command(client,scope,'confirm_statement_account',payment['object_id'],payment_result['artifact']['version'],'confirm-procurement-account',
                       {'token':candidate['token'],'ownership_confirmed':True,'note':'合成测试账户归属已核对',
                        'new_account':{'account_number':'00123456789','holder':'合成企业','bank_name':'合成银行','currency':'CNY'}})
    assert response.status_code==200,response.text
    payment_fact=response.json()['effect']['facts'][0]
    contract = uploaded(client, scope, xlsx_fixture([("合同", [["合同编号", "合同日期", "供应商名称", "合同金额"], ["HT-001", "2026-03-05", "供应商A", "113.00"]])]), filename="合同.xlsx")
    contract_fact = parse(client, scope, contract, kind="contract", key="parse-procurement-contract").json()["effect"]["facts"][0]
    stock_in = uploaded(client, scope, xlsx_fixture([("入库", [["入库单号", "入库日期", "供应商名称", "入库金额"], ["RK-001", "2026-03-06", "供应商A", "113.00"]])]), filename="入库.xlsx")
    stock_fact = parse(client, scope, stock_in, kind="stock_in", key="parse-procurement-stock-in").json()["effect"]["facts"][0]

    response = client.post("/api/v1/business/procurement", json={
        "scope": scope,
        "fact_ids": [invoice_fact["object_id"], payment_fact["object_id"], contract_fact["object_id"], stock_fact["object_id"]],
        "business_identity": "procurement-with-all-evidence", "idempotency_key": "procurement-all-evidence",
    })
    assert response.status_code == 200, response.text
    group = response.json()["effect"]["object"]
    assert group["data"]["missing_evidence"] == []
    assert group["data"]["evidence_grade"] == "A"
