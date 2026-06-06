from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.core.org_context import ensure_default_organization
from app.main import create_app
from app.models import Enterprise


ORG = UUID("00000000-0000-0000-0000-000000000001")


def make_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    db_session = TestingSession()
    ensure_default_organization(db_session)
    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=False), db_session


def make_enterprise(db_session, name="苏州科技画像测试有限公司"):
    enterprise = Enterprise(
        organization_id=ORG,
        name=name,
        unified_social_credit_code="91320500TECH000001",
        taxpayer_type="GENERAL",
        industry="制造业",
    )
    db_session.add(enterprise)
    db_session.commit()
    db_session.refresh(enterprise)
    return enterprise


def test_get_technology_profile_creates_not_scanned_profile():
    client, db_session = make_context()
    enterprise = make_enterprise(db_session)

    response = client.get(f"/api/enterprises/{enterprise.id}/technology-profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enterprise_id"] == str(enterprise.id)
    assert payload["overall_status"] == "NOT_SCANNED"
    assert payload["tags"] == []


def test_upsert_scan_results_is_idempotent_and_preserves_evidence():
    client, db_session = make_context()
    enterprise = make_enterprise(db_session)
    payload = {
        "provider": "QICHACHA",
        "summary": "命中高新技术企业，存在发明专利 2 件。",
        "raw_snapshot": {"source": "qcc", "safe": True},
        "tags": [
            {
                "category": "TECH_QUALIFICATION",
                "name": "高新技术企业",
                "status": "HIT",
                "value": "有效期内",
                "confidence": 95,
                "source_url": "https://www.qcc.com/firm/example",
                "evidence_text": "高新技术企业",
            },
            {
                "category": "INTELLECTUAL_PROPERTY",
                "name": "发明专利",
                "status": "HIT",
                "value": "2",
                "confidence": 90,
                "source_url": "https://www.qcc.com/firm/example",
                "evidence_text": "发明专利 2",
            },
        ],
    }

    first = client.post(f"/api/enterprises/{enterprise.id}/technology-profile/scan-results", json=payload)
    second = client.post(f"/api/enterprises/{enterprise.id}/technology-profile/scan-results", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    data = second.json()
    assert data["overall_status"] == "SCANNED_PENDING_REVIEW"
    assert data["primary_provider"] == "QICHACHA"
    assert data["summary"] == "命中高新技术企业，存在发明专利 2 件。"
    assert len(data["tags"]) == 2
    high_tech = next(tag for tag in data["tags"] if tag["name"] == "高新技术企业")
    assert high_tech["source_provider"] == "QICHACHA"
    assert high_tech["confidence"] == 95
    assert high_tech["evidence_text"] == "高新技术企业"


def test_upsert_scan_results_accepts_qichacha_innovation_text():
    client, db_session = make_context()
    enterprise = make_enterprise(db_session)

    response = client.post(
        f"/api/enterprises/{enterprise.id}/technology-profile/scan-results",
        json={
            "provider": "QICHACHA",
            "source_url": "https://www.qcc.com/firm/example.html",
            "qichacha_innovation_text": (
                "科创分 72\n"
                "良好\n"
                "科技型企业认定情况 1\n"
                "1 科技型中小企业 国家级 ✓\n"
                "2 高新技术企业 ×\n"
                "知识产权取得情况\n"
                "有效发明专利\n"
                "1\n"
                "软件著作权\n"
                "3"
            ),
        },
    )

    assert response.status_code == 200
    tags = {tag["name"]: tag for tag in response.json()["tags"]}
    assert tags["科技型中小企业"]["category"] == "QCC_TECH_CERTIFICATION"
    assert tags["科技型中小企业"]["source_url"] == "https://www.qcc.com/firm/example.html"
    assert "高新技术企业" not in tags
    assert tags["有效发明专利"]["category"] == "QCC_INTELLECTUAL_PROPERTY"
    assert tags["有效发明专利"]["value"] == "1"
    assert tags["软件著作权"]["value"] == "3"


def test_confirm_and_reject_pending_technology_tags():
    client, db_session = make_context()
    enterprise = make_enterprise(db_session)
    response = client.post(
        f"/api/enterprises/{enterprise.id}/technology-profile/scan-results",
        json={
            "provider": "TIANYANCHA",
            "summary": "发现疑似科技型中小企业。",
            "tags": [
                {
                    "category": "TECH_QUALIFICATION",
                    "name": "科技型中小企业",
                    "status": "PENDING_REVIEW",
                    "confidence": 68,
                    "evidence_text": "页面存在科技型中小企业相关字段",
                },
                {
                    "category": "SERVICE_OPPORTUNITY",
                    "name": "高新技术企业申报",
                    "status": "PENDING_REVIEW",
                    "confidence": 60,
                    "evidence_text": "存在知识产权和研发相关迹象",
                },
            ],
        },
    )
    tags = response.json()["tags"]
    tech_tag = next(tag for tag in tags if tag["name"] == "科技型中小企业")
    opportunity_tag = next(tag for tag in tags if tag["name"] == "高新技术企业申报")

    confirm_response = client.post(f"/api/technology-tags/{tech_tag['id']}/confirm")
    reject_response = client.post(f"/api/technology-tags/{opportunity_tag['id']}/reject")

    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "HIT"
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "NOT_HIT"
