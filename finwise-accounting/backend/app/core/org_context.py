from uuid import UUID

from app.core.config import get_settings


def get_current_organization_id() -> UUID:
    return UUID(get_settings().default_organization_id)
