from __future__ import annotations

import logging
import time

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.main import initialize_database
from app.services.voucher_preprocess_job_service import process_next_voucher_preprocess_batch


LOGGER = logging.getLogger(__name__)


def main() -> None:
    initialize_database()
    poll_seconds = max(0.2, get_settings().voucher_ai_worker_poll_seconds)
    while True:
        try:
            with SessionLocal() as db:
                processed = process_next_voucher_preprocess_batch(db)
        except Exception:
            LOGGER.exception("Voucher AI preprocess worker iteration failed")
            processed = False
        if not processed:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
