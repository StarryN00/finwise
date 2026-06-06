import json
from pathlib import Path
from uuid import UUID

from app.models import Enterprise, TechnologyTag
from scripts.import_technology_profiles import import_profiles_from_file


ORG = UUID("00000000-0000-0000-0000-000000000001")


def test_import_profiles_from_json_is_idempotent(db_session, tmp_path: Path):
    enterprise = Enterprise(
        organization_id=ORG,
        name="苏州脚本导入测试有限公司",
        unified_social_credit_code="91320500SCRIPT0001",
        taxpayer_type="GENERAL",
        industry="制造业",
    )
    db_session.add(enterprise)
    db_session.commit()
    data_file = tmp_path / "technology_profiles.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "enterprise_name": enterprise.name,
                    "provider": "QICHACHA",
                    "summary": "命中高新技术企业，软著 3 件。",
                    "tags": [
                        {
                            "category": "TECH_QUALIFICATION",
                            "name": "高新技术企业",
                            "status": "HIT",
                            "value": "有效期内",
                            "confidence": 95,
                            "evidence_text": "高新技术企业",
                        },
                        {
                            "category": "INTELLECTUAL_PROPERTY",
                            "name": "软著",
                            "status": "HIT",
                            "value": "3",
                            "confidence": 90,
                            "evidence_text": "软件著作权 3 件",
                        },
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = import_profiles_from_file(db_session, data_file)
    second = import_profiles_from_file(db_session, data_file)

    assert first["updated"] == 1
    assert second["updated"] == 1
    assert db_session.query(TechnologyTag).filter(TechnologyTag.enterprise_id == enterprise.id).count() == 2


def test_import_profiles_from_qichacha_innovation_text_keeps_qcc_native_structure(db_session, tmp_path: Path):
    enterprise = Enterprise(
        organization_id=ORG,
        name="苏州科创文本测试有限公司",
        unified_social_credit_code="91320500QCC0001",
        taxpayer_type="GENERAL",
        industry="研究和试验发展",
    )
    db_session.add(enterprise)
    db_session.commit()
    data_file = tmp_path / "qichacha_text.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "enterprise_name": enterprise.name,
                    "provider": "QICHACHA",
                    "source_url": "https://www.qcc.com/firm/example.html",
                    "qichacha_innovation_text": "科创分 72\n良好\n科技型企业认定情况 1\n1 科技型中小企业 国家级 ✓\n2 高新技术企业 ×\n知识产权取得情况\n有效发明专利\n1\n软件著作权\n3",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = import_profiles_from_file(db_session, data_file)

    assert result["updated"] == 1
    tags = {
        tag.name: tag
        for tag in db_session.query(TechnologyTag).filter(TechnologyTag.enterprise_id == enterprise.id).all()
    }
    assert tags["科技型中小企业"].status == "HIT"
    assert tags["科技型中小企业"].category == "QCC_TECH_CERTIFICATION"
    assert "高新技术企业" not in tags
    assert tags["有效发明专利"].value == "1"
    assert tags["有效发明专利"].category == "QCC_INTELLECTUAL_PROPERTY"
    assert tags["软件著作权"].value == "3"
