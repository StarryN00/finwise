from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfReader

from finreport.analyzer import compute_all_metrics
from finreport.main import generate_finhealth_report


SAMPLE_PATH = Path("finreport/tests/sample_input.json")


def load_sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def test_analyzer_reclassifies_negative_liabilities_and_rates():
    metrics = compute_all_metrics(load_sample())

    adjusted_2025 = metrics["statements"]["adjusted"]["2025"]
    risk = metrics["risks"]

    assert adjusted_2025["预付性质款项"] == 3554100.0
    assert adjusted_2025["负债合计"] == 3000000.0
    assert adjusted_2025["流动资产"] == 5407600.0
    assert risk["现金比率"]["level"] == "高风险"
    assert risk["资产负债率"]["value"] == metrics["capital_structure"]["2025"]["资产负债率"]
    assert round(metrics["profitability"]["2025"]["净利率"], 4) == -0.2591
    assert len(metrics["potential_losses"]) == 6
    assert metrics["potential_losses"][-1]["项目"] == "合计"


def test_finreport_full_pipeline_generates_20_page_pdf(tmp_path, monkeypatch):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)

    pdf_path = generate_finhealth_report(load_sample(), output_dir=str(tmp_path))

    path = Path(pdf_path)
    assert path.exists()
    assert path.name.startswith("财务健康诊断报告_苏州XX环保设备有限公司_2026年4月")
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    compact_text = text.replace(" ", "")
    assert len(reader.pages) == 20
    assert "FINANCIALHEALTHDIAGNOSTIC" in compact_text
    assert "企业财务健康诊断报告" in text
    assert "总结展望" in text


def test_finreport_pdf_embeds_real_chart_images(tmp_path, monkeypatch):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)

    pdf_path = generate_finhealth_report(load_sample(), output_dir=str(tmp_path))

    reader = PdfReader(pdf_path)
    for page_index in [4, 6, 8, 12]:
        xobjects = (reader.pages[page_index].get("/Resources") or {}).get("/XObject")
        assert xobjects is not None
        image_sizes = []
        for key in xobjects.keys():
            obj = xobjects[key].get_object()
            if obj.get("/Subtype") == "/Image":
                image_sizes.append((int(obj.get("/Width")), int(obj.get("/Height"))))
        assert image_sizes
        assert max(width for width, _height in image_sizes) > 500
