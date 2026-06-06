from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.core.org_context import ensure_default_organization
from app.main import create_app
from app.models import Enterprise, TechnologyScanJob, TechnologyScanJobItem, TechnologyTag


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


def make_enterprise(db_session, name: str, code: str):
    enterprise = Enterprise(
        organization_id=ORG,
        name=name,
        unified_social_credit_code=code,
        taxpayer_type="GENERAL",
        industry="制造业",
    )
    db_session.add(enterprise)
    db_session.commit()
    db_session.refresh(enterprise)
    return enterprise


def test_create_scan_job_for_selected_enterprises():
    client, db_session = make_context()
    first = make_enterprise(db_session, "昆山批量扫描一号有限公司", "91320500BATCH0001")
    second = make_enterprise(db_session, "昆山批量扫描二号有限公司", "91320500BATCH0002")

    response = client.post(
        "/api/technology-scan-jobs",
        json={
            "provider": "QICHACHA",
            "scope_type": "SELECTED",
            "enterprise_ids": [str(first.id), str(second.id)],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "QICHACHA"
    assert payload["scope_type"] == "SELECTED"
    assert payload["status"] == "PENDING"
    assert payload["target_enterprise_count"] == 2
    assert [item["enterprise_name"] for item in payload["items"]] == [first.name, second.name]
    assert db_session.query(TechnologyScanJob).count() == 1
    assert db_session.query(TechnologyScanJobItem).count() == 2


def test_create_scan_job_for_unscanned_enterprises_only():
    client, db_session = make_context()
    unscanned = make_enterprise(db_session, "昆山未扫描有限公司", "91320500UNSCANNED1")
    scanned = make_enterprise(db_session, "昆山已扫描有限公司", "91320500SCANNED01")
    client.post(
        f"/api/enterprises/{scanned.id}/technology-profile/scan-results",
        json={
            "provider": "QICHACHA",
            "summary": "已扫描。",
            "tags": [
                {
                    "category": "QCC_TECH_CERTIFICATION",
                    "name": "科技型中小企业",
                    "status": "HIT",
                    "confidence": 95,
                    "evidence_text": "科技型中小企业",
                }
            ],
        },
    )

    response = client.post(
        "/api/technology-scan-jobs",
        json={"provider": "QICHACHA", "scope_type": "UNSCANNED"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_enterprise_count"] == 1
    assert payload["items"][0]["enterprise_id"] == str(unscanned.id)


def test_scan_job_item_lifecycle_writes_profile_and_counts():
    client, db_session = make_context()
    enterprise = make_enterprise(db_session, "昆山任务完成有限公司", "91320500JOBDONE01")
    job = client.post(
        "/api/technology-scan-jobs",
        json={"provider": "QICHACHA", "scope_type": "SELECTED", "enterprise_ids": [str(enterprise.id)]},
    ).json()
    item_id = job["items"][0]["id"]

    running = client.post(f"/api/technology-scan-jobs/{job['id']}/items/{item_id}/mark-running")
    completed = client.post(
        f"/api/technology-scan-jobs/{job['id']}/items/{item_id}/complete",
        json={
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

    assert running.status_code == 200
    assert completed.status_code == 200
    payload = completed.json()
    assert payload["status"] == "COMPLETED"
    assert payload["completed_enterprise_count"] == 1
    assert payload["items"][0]["status"] == "COMPLETED"
    tags = {
        tag.name: tag
        for tag in db_session.query(TechnologyTag).filter(TechnologyTag.enterprise_id == enterprise.id).all()
    }
    assert tags["科技型中小企业"].category == "QCC_TECH_CERTIFICATION"
    assert "高新技术企业" not in tags
    assert tags["软件著作权"].value == "3"


def test_scan_job_can_fail_item_and_pause():
    client, db_session = make_context()
    enterprise = make_enterprise(db_session, "昆山任务失败有限公司", "91320500JOBFAIL01")
    job = client.post(
        "/api/technology-scan-jobs",
        json={"provider": "QICHACHA", "scope_type": "SELECTED", "enterprise_ids": [str(enterprise.id)]},
    ).json()
    item_id = job["items"][0]["id"]

    failed = client.post(
        f"/api/technology-scan-jobs/{job['id']}/items/{item_id}/fail",
        json={"failure_reason": "CAPTCHA_REQUIRED", "error_summary": "企查查要求验证码。"},
    )
    paused = client.post(
        f"/api/technology-scan-jobs/{job['id']}/pause",
        json={"failure_reason": "LOGIN_REQUIRED", "error_summary": "登录态失效。"},
    )

    assert failed.status_code == 200
    failed_payload = failed.json()
    assert failed_payload["status"] == "PARTIAL_FAILED"
    assert failed_payload["review_required_count"] == 1
    assert failed_payload["items"][0]["failure_reason"] == "CAPTCHA_REQUIRED"
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"
