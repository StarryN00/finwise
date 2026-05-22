from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.initial_statement_service import parse_initial_statement


def write_statement(path: Path, rows: list[list[object]]) -> Path:
    pd.DataFrame(rows).to_excel(path, header=False, index=False)
    return path


def test_parse_balance_sheet_extracts_key_subjects(tmp_path):
    path = write_statement(
        tmp_path / "balance.xlsx",
        [
            ["项目", "行次", "期末余额"],
            ["货币资金", "1", 614277.56],
            ["资产总计", "30", 908486.12],
            ["负债合计", "47", 952699.44],
            ["所有者权益合计", "52", -44213.32],
        ],
    )

    result = parse_initial_statement(path, statement_type="BALANCE_SHEET")

    assert result["data"] == {
        "货币资金": "614277.56",
        "资产总计": "908486.12",
        "负债合计": "952699.44",
        "所有者权益合计": "-44213.32",
    }
    assert result["missing_fields"] == []


def test_parse_income_statement_extracts_key_subjects(tmp_path):
    path = write_statement(
        tmp_path / "income.xlsx",
        [
            ["项目", "行次", "本月金额"],
            ["营业收入", "1", 251415.93],
            ["营业成本", "2", 226274.34],
            ["管理费用", "14", 10387.26],
            ["净利润", "32", 14754.33],
        ],
    )

    result = parse_initial_statement(path, statement_type="INCOME_STATEMENT")

    assert result["data"] == {
        "营业收入": "251415.93",
        "营业成本": "226274.34",
        "管理费用": "10387.26",
        "净利润": "14754.33",
    }
    assert result["missing_fields"] == []


def test_parse_initial_statement_endpoint_accepts_uploaded_excel(tmp_path):
    path = write_statement(
        tmp_path / "balance.xlsx",
        [["项目", "期末余额"], ["资产总计", 100], ["负债合计", 40], ["所有者权益合计", 60]],
    )
    client = TestClient(create_app(init_db_on_startup=False))

    with path.open("rb") as file:
        response = client.post(
            "/api/initial-statements/parse",
            data={"statement_type": "BALANCE_SHEET"},
            files={"file": ("balance.xlsx", file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["资产总计"] == "100.00"
    assert payload["data"]["负债合计"] == "40.00"
    assert payload["data"]["所有者权益合计"] == "60.00"
