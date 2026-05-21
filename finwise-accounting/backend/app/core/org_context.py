from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import DEFAULT_CHANNEL_ID, Organization


def get_current_organization_id() -> UUID:
    return UUID(get_settings().default_organization_id)


def ensure_default_organization(db: Session) -> Organization:
    organization_id = get_current_organization_id()
    organization = db.get(Organization, organization_id)
    if organization is not None:
        return organization

    organization = Organization(
        id=organization_id,
        channel_id=DEFAULT_CHANNEL_ID,
        name="默认代账机构",
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization
