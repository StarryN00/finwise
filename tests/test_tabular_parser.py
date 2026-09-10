"""Synthetic fixtures aligned with read-only inspection of staging payroll headers."""
from io import BytesIO

import openpyxl
import pytest

from app.tabular import PARSER_VERSION, ParseOptions, extract_workbook, read_workbook
from app.ontology.procurement import procurement_amounts
from app.materials import compare_fields
from test_tabular_ingestion import INVOICE_HEADERS, xlsx_fixture, uploaded, parse


def workbook(rows, merges=(), sheet="资料"):
    book = openpyxl.Workbook()
    page = book.active
    page.title = sheet
    for row in rows:
        page.append(row)
    for region in merges:
        page.merge_cells(region)
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def extract(content, kind="payroll", period="2026-01"):
    return extract_workbook(content, ParseOptions(document_kind=kind), period)["records"]


@pytest.mark.parametrize("kind", ["purchase_invoices", "sales_invoices"])
@pytest.mark.parametrize("rate,status", [(None, "MISSING"), ("  ", "MISSING"), ("bad", "INVALID"), (True, "INVALID"),
                                         ("NaN", "INVALID"), ("101%", "INVALID"), ("-1%", "INVALID"), ("0%", "EXPLICIT")])
def test_rate_missing_invalid_and_explicit_are_distinct(kind, rate, status):
    fact = extract(workbook([INVOICE_HEADERS, ["I-1", "2026-01-01", "100", "0", rate, "合成供应商"]]), kind)[0]
    assert fact["field_sources"]["tax_rate"]["status"] == status
    assert fact["normalized_value"]["tax"] == "0.00"
    assert fact["normalized_value"]["tax_rate"] == ("0" if status == "EXPLICIT" else None)
    assert bool(fact["extraction_issues"]) == (status == "INVALID")
    assert fact["field_sources"]["tax_rate"]["raw_value"] == rate
    assert fact["field_sources"]["tax_rate"]["label"] == "税率"


def test_absent_rate_column_is_extractable_but_existing_tax_gate_still_blocks(client, scope):
    content = xlsx_fixture([("发票", [["发票号码", "开票日期", "金额", "税额"],
                                      ["I-1", "2026-03-01", "100", "12.34"]])])
    fact = parse(client, scope, uploaded(client, scope, content)).json()["effect"]["facts"][0]
    assert fact["status"] == "PARSED"
    data = fact["data"]
    assert data["parser_version"] == PARSER_VERSION == "tabular-v5"
    assert data["normalized_value"]["tax"] == "12.34"
    assert data["normalized_value"]["tax_rate"] is None
    assert data["field_sources"]["tax_rate"]["region"] == ""
    compared = next(row for row in compare_fields(data) if row["field"] == "tax_rate")
    assert compared["state"] == "MISSING" and compared["source_label"] == "税率"
    assert procurement_amounts([fact])["tax_valid"] is False


@pytest.mark.parametrize("tax,has_issue", [("12.00", True), ("13.00", False), ("13.01", False), ("13.02", True)])
def test_explicit_rate_checks_tax_with_existing_cent_tolerance(tax, has_issue):
    fact = extract(workbook([INVOICE_HEADERS, ["I-1", "2026-01-01", "100", tax, "13%", "供应商"]]), "purchase_invoices")[0]
    assert fact["normalized_value"]["tax"] == tax
    assert any("明确税率不一致" in issue for issue in fact["extraction_issues"]) == has_issue


def staging_shaped_payroll():
    # Real source layout only; names and all amounts are synthetic. No staging parsing.
    rows = [[None]*35 for _ in range(10)]
    rows[6][33] = "月份:2026.1月工资条"
    for column, value in {0:"姓名", 1:"基本工资", 24:"单位缴", 25:"个人缴", 26:"单位缴", 27:"个人缴", 31:"应扣", 33:"实发工资", 34:"签字"}.items():
        rows[7][column] = value
    for column, value in {24:"公司\n社保", 25:"个人\n社保", 26:"公积金\n公司/个人", 31:"个税"}.items():
        rows[8][column] = value
    for column, value in {0:"合成员工", 1:5000, 24:900, 25:300, 26:250, 27:200, 31:10, 33:4490}.items():
        rows[9][column] = value
    return workbook(rows, ["A8:A9", "B8:B9", "AH8:AH9", "AA9:AB9"])


def test_real_header_shape_preserves_four_amounts_and_merged_provenance(client, scope):
    content = staging_shaped_payroll()
    assert (27, 9, 28, 9) in read_workbook(content)[0]["merged_cells"]
    source = uploaded(client, scope, content, filename="合成工资.xlsx")
    fact = parse(client, scope, source, kind="payroll").json()["effect"]["facts"][0]
    data = fact["data"]
    assert data["extraction_issues"] == []
    expected = {"employer_social": ("900.00", "Y10"), "employee_social": ("300.00", "Z10"),
                "employer_housing_fund": ("250.00", "AA10"), "employee_housing_fund": ("200.00", "AB10")}
    for field, (amount, cell) in expected.items():
        assert data["normalized_value"][field] == amount
        assert data["field_sources"][field]["region"] == "资料!" + cell
        assert data["field_sources"][field]["rawvalue"] == float(amount)
    assert data["normalized_value"]["housing_fund"] is None
    assert data["normalized_value"]["tax"] == "10.00"
    path = data["field_sources"]["employee_housing_fund"]["header_path"]
    assert [(p["region"], p["raw_value"]) for p in path] == [("资料!AB8", "个人缴"), ("资料!AA9:AB9", "公积金\n公司/个人")]
    assert data["original_value"]["header_rows"][1]["values"][27] is None
    assert data["original_value"]["headers"][27] == "个人缴"
    assert data["field_sources"]["period"]["region"] == "资料!AH7"
    assert data["field_sources"]["period"]["raw_value"] == "月份:2026.1月工资条"
    comparison = {row["field"]: row for row in compare_fields(data)}
    assert comparison["employee_housing_fund"]["source_value"] == 200
    assert "个人缴" in comparison["employee_housing_fund"]["source_label"]
    assert "公积金" in comparison["employee_housing_fund"]["source_label"]
    assert comparison["employee_housing_fund"]["state"] == "NORMALIZED_MATCH"
    assert comparison["period"]["source_value"] == "月份:2026.1月工资条"
    assert comparison["period"]["state"] == "DERIVED"
    assert "从工资表标题提取年月" in comparison["period"]["derivation"]
    assert data["normalized_value"]["period"] == "2026-01"
    assert fact["status"] == "PERIOD_EXCEPTION"  # March scope cannot change January evidence.


def test_group_above_side_headers_and_reordered_repeated_blocks():
    content = workbook([
        ["月份:2026.1月工资条"],
        ["姓名", "实发工资", "社保", None, "公积金", None],
        [None, None, "单位缴", "个人缴", "单位缴", "个人缴"],
        ["员工甲", 1000, 111, 22, 33, 44],
        ["月份:2026.2月工资条"],
        ["姓名", "实发工资", "公积金", None, "社保", None],
        [None, None, "个人缴", "单位缴", "个人缴", "单位缴"],
        ["员工乙", 1000, 55, 66, 77, 88],
    ], ["A2:A3", "B2:B3", "C2:D2", "E2:F2", "A6:A7", "B6:B7", "C6:D6", "E6:F6"])
    first, second = extract(content)
    assert first["normalized_value"]["employer_social"] == "111.00"
    assert second["normalized_value"]["employer_social"] == "88.00"
    assert second["normalized_value"]["employee_housing_fund"] == "55.00"
    assert second["field_sources"]["period"]["region"] == "资料!A5"
    assert first["period_check"] == "PASS" and second["period_check"] == "PERIOD_EXCEPTION"


@pytest.mark.parametrize("headers", [["单位缴", "个人缴", "单位缴", "个人缴"],
                                      ["公司社保", "公司社保", "单位缴", "个人缴"]])
def test_ambiguous_generic_or_duplicate_columns_never_select_first(headers):
    fact = extract(workbook([["月份:2026.1月工资条"], ["姓名", "实发工资", *headers], ["员工", 1000, 11, 22, 33, 44]]))[0]
    assert fact["normalized_value"]["employer_social"] is None
    assert fact["normalized_value"]["employee_social"] is None
    assert fact["normalized_value"]["employer_housing_fund"] is None
    assert any("unmapped_C" in issue and "资料!C3" in issue for issue in fact["extraction_issues"])
    assert fact["field_sources"]["unmapped_C"]["raw_value"] == 11
    assert fact["field_sources"]["unmapped_C"]["status"] == "AMBIGUOUS"


@pytest.mark.parametrize("title,status", [(None, "MISSING"), ("打印日期2026年1月", "MISSING"),
                                         ("月份:2026.1月及2026.2月工资条", "AMBIGUOUS"),
                                         ("月份:待确认", "AMBIGUOUS")])
def test_payroll_period_requires_unambiguous_local_business_source(title, status):
    fact = extract(workbook([[title], ["姓名", "实发工资"], ["员工", 1000]]))[0]
    assert fact["normalized_value"]["period"] is None
    assert fact["period_check"] == "PERIOD_EXCEPTION"
    assert fact["field_sources"]["period"]["status"] == status
    assert any(issue.startswith("period：") for issue in fact["extraction_issues"])


def test_other_sheet_title_cannot_supply_payroll_period():
    content = xlsx_fixture([("说明", [["月份:2026.1月工资条"]]), ("工资", [["姓名", "实发工资"], ["员工", "1000"]])])
    fact = extract(content)[0]
    assert fact["normalized_value"]["period"] is None
    assert fact["period_check"] == "PERIOD_EXCEPTION"


def test_blank_and_formula_contributions_keep_source_without_inventing_zero():
    fact = extract(workbook([["月份:2026.1月工资条"],
                            ["姓名", "实发工资", "公司社保", "个人公积金"],
                            ["员工", 1000, None, "=100+20"]]))[0]
    assert fact["normalized_value"]["employer_social"] is None
    assert fact["normalized_value"]["employee_housing_fund"] is None
    assert fact["field_sources"]["employer_social"]["region"] == "资料!C3"
    assert fact["field_sources"]["employee_housing_fund"]["formula"] == "=100+20"
    assert any("公式值" in issue for issue in fact["extraction_issues"])


def test_unmerged_blank_group_is_not_filled_from_left():
    fact = extract(workbook([["月份:2026.1月工资条"],
                            ["姓名", "实发工资", "社保", None],
                            [None, None, "单位缴", "个人缴"],
                            ["员工", 1000, 100, 20]], ["A2:A3", "B2:B3"]))[0]
    assert fact["normalized_value"]["employer_social"] == "100.00"
    assert fact["normalized_value"]["employee_social"] is None
    assert any("unmapped_D" in issue for issue in fact["extraction_issues"])


def test_contribution_base_is_not_mapped_as_contribution_amount():
    fact = extract(workbook([["月份:2026.1月工资条"],
                            ["姓名", "实发工资", "公司社保基数"], ["员工", 1000, 5000]]))[0]
    assert fact["normalized_value"]["employer_social"] is None
    assert any("unmapped_C" in issue for issue in fact["extraction_issues"])


def test_missing_rate_formula_is_not_silently_accepted_as_absent_column():
    fact = extract(workbook([INVOICE_HEADERS, ["I-1", "2026-01-01", "100", "13", "=13/100", "供应商"]]), "purchase_invoices")[0]
    assert fact["normalized_value"]["tax_rate"] is None
    assert fact["field_sources"]["tax_rate"]["formula"] == "=13/100"
    assert any("tax_rate：公式值" in issue for issue in fact["extraction_issues"])


@pytest.mark.parametrize("bad_salary", ["not money", None, "=1000-20"])
def test_invalid_employee_salary_is_retained_and_explanatory_rows_are_excluded(client, scope, bad_salary):
    content = workbook([["月份:2026.3月工资条"], ["姓名", "实发工资"],
                        ["甲", 1000], ["乙", bad_salary], ["说明：实发金额待核对"],
                        ["备注：包含补发"], ["合成企业有限公司"], ["薪资计算说明"],
                        ["公司社保"], ["这是合并的工资说明"], ["合计", 1000]], ["A10:B10"])
    result = parse(client, scope, uploaded(client, scope, content), kind="payroll").json()["effect"]
    assert result["counts"] == {"rows": 2, "parsed": 1, "needs_review": 1, "period_exception": 0}
    good, bad = result["facts"]
    assert good["data"]["normalized_value"]["person_name"] == "甲"
    assert bad["data"]["normalized_value"]["person_name"] == "乙"
    assert bad["status"] == "NEEDS_REVIEW"
    assert bad["data"]["normalized_value"]["actual_salary"] is None
    source = bad["data"]["field_sources"]["actual_salary"]
    assert source["region"] == "资料!B4"
    assert source["formula"] == (bad_salary if str(bad_salary).startswith("=") else None)
    assert source["original_value"] == (None if str(bad_salary).startswith("=") else bad_salary)
    assert any(issue.startswith("actual_salary：") for issue in bad["data"]["extraction_issues"])


def test_dated_payroll_notes_excluded_without_losing_fourteen_employee_rows(client, scope):
    rows = [[None, None] for _ in range(116)]
    rows[0] = ["月份:2026.3月工资条"]
    rows[1] = ["姓名", "实发工资"]
    employee_rows = [10, 18, 25, 33, 41, 49, 60, 69, 76, 84, 92, 101, 108, 116]
    for number in employee_rows:
        rows[number-1] = [f"合成员工{number}", 1000]
    rows[9][1], rows[17][1] = "not money", None
    for number, note in {
        44: "24/10/27入职，8500/月",
        72: "25/3/21上班 薪资4000，2025.8月涨800",
        96: "22.9月调6000+300",
        97: "23.7月调7500  23.12调8000",
    }.items():
        rows[number-1] = [note, None]
    result = parse(client, scope, uploaded(client, scope, workbook(rows)), kind="payroll").json()["effect"]
    assert result["counts"] == {"rows": 14, "parsed": 12, "needs_review": 2, "period_exception": 0}
    assert [fact["data"]["source_anchor"]["row"] for fact in result["facts"]] == employee_rows
    assert all(fact["status"] == "NEEDS_REVIEW" for fact in result["facts"][:2])
    assert result["facts"][0]["data"]["field_sources"]["actual_salary"]["original_value"] == "not money"


@pytest.mark.parametrize("name,salary", [
    ("员工甲", None), ("员工乙", "not money"),
    ("24/10/27待核对人员", None), ("入职员工", None),
    ("24/10/27入职，8500/月", "not money"),
    ("22.9月调6000+300", 1000), ("22.9月调6000+300", "=1000"),
])
def test_note_filter_requires_date_semantics_and_empty_nonformula_salary(name, salary):
    facts = extract(workbook([["月份:2026.1月工资条"], ["姓名", "实发工资"], [name, salary]]))
    assert len(facts) == 1
    assert facts[0]["normalized_value"]["person_name"] == name
    if salary != 1000:
        assert any(issue.startswith("actual_salary：") for issue in facts[0]["extraction_issues"])


@pytest.mark.parametrize("header", ["社保", "社会保险"])
def test_social_column_without_payer_is_not_system_checked(client, scope, header):
    content = workbook([["月份:2026.3月工资条"], ["姓名", "实发工资", header], ["甲", 1000, 200]])
    result = parse(client, scope, uploaded(client, scope, content), kind="payroll").json()["effect"]
    fact = result["facts"][0]
    assert fact["status"] == "NEEDS_REVIEW"
    assert fact["data"]["normalized_value"]["employer_social"] is None
    assert fact["data"]["normalized_value"]["employee_social"] is None
    source = fact["data"]["field_sources"]["unmapped_C"]
    assert source["original_value"] == 200 and source["source_label"] == header
    assert source["region"] == "资料!C3"
    assert any("未明确单位或个人缴费方" in issue for issue in fact["data"]["extraction_issues"])
    from app.ontology.contracts import Scope
    review = client.app.state.service.workbench(Scope(**scope))["material_review"]
    assert review["counts"]["system_checked"] == 0
    assert review["counts"]["needs_review"] == 1


def test_xls_formatting_width_does_not_change_anchor_or_fact_identity(monkeypatch, client, scope):
    """Model xlrd's observed 35/44-column split; exercise the real upgrade command."""
    from types import SimpleNamespace
    import xlrd
    import app.ontology.service as ontology_service

    fixture = read_workbook(staging_shaped_payroll())[0]
    fixture["rows"][6]["values"][33] = "月份:2026.3月工资条"
    released, opened = [], []

    def open_xls(*, file_contents, on_demand, formatting_info=False):
        opened.append(formatting_info)
        width = 44 if formatting_info else 35
        def row(index):
            values = fixture["rows"][index]["values"]
            return [SimpleNamespace(value=value if value is not None else "",
                                    ctype=xlrd.XL_CELL_EMPTY if value is None else xlrd.XL_CELL_NUMBER if isinstance(value, (int, float)) else xlrd.XL_CELL_TEXT)
                    for value in values + [None]*(width-len(values))]
        sheet = SimpleNamespace(name="资料", nrows=10, ncols=width, row=row,
                                merged_cells=[(r1-1, r2, c1-1, c2) for c1, r1, c2, r2 in fixture["merged_cells"]] if formatting_info else [])
        return SimpleNamespace(nsheets=1, datemode=0, sheets=lambda: [sheet], sheet_by_index=lambda _: sheet,
                               release_resources=lambda: released.append(formatting_info))

    monkeypatch.setattr(xlrd, "open_workbook", open_xls)
    content = bytes.fromhex("d0cf11e0a1b11ae1") + b"synthetic-xlrd-width-boundary"
    source = uploaded(client, scope, content, filename="合成工资.xls")
    legacy_record = {
        "record_type": "PAYROLL", "source_anchor": {"row": 10, "region": "资料!A10:AI10"},
        "original_value": {"sheet": "资料", "row": 10, "headers": fixture["rows"][7]["values"], "values": fixture["rows"][9]["values"]},
        "normalized_value": {"person_name": "合成员工", "actual_salary": "4490.00", "period": "2026-03"},
        "field_sources": {}, "extraction_issues": [], "extraction_confidence": 1.0, "period_check": "PASS",
    }
    with monkeypatch.context() as legacy:
        legacy.setattr(ontology_service, "PARSER_VERSION", "tabular-v3")
        legacy.setattr(ontology_service, "extract_workbook", lambda *args: {"records": [legacy_record], "sheets": [], "errors": []})
        before = parse(client, scope, source, kind="payroll", key="legacy-payroll").json()["effect"]
    assert before["artifact"]["data"]["parse_version"] == "tabular-v3"
    after = parse(client, scope, before["artifact"], kind="payroll", key="upgrade-payroll").json()["effect"]
    assert after["counts"]["rows"] == 1
    old, new = before["facts"][0], after["facts"][0]
    assert new["object_id"] == old["object_id"]
    assert new["version"] > old["version"]
    assert new["data"]["parser_version"] == "tabular-v5"
    assert new["data"]["source_anchor"] == old["data"]["source_anchor"]
    assert len(new["data"]["original_value"]["headers"]) == 35
    assert len(new["data"]["original_value"]["values"]) == 35
    assert new["data"]["normalized_value"]["employee_housing_fund"] == "200.00"
    assert new["data"]["field_sources"]["employee_housing_fund"]["header_path"][1]["region"] == "资料!AA9:AB9"
    assert opened == [False, True] and released == [False, True]
