import asyncio
import logging

from app.db.session import SessionLocal
from app.services.market_engine import run_periodic_jobs

logger = logging.getLogger(__name__)
SCHEDULER_INTERVAL_SECONDS = 60


def run_once() -> None:
    db = SessionLocal()
    try:
        results = run_periodic_jobs(db)
        if any(results.values()):
            logger.info("Procesos económicos periódicos ejecutados: %s", results)
    except Exception:
        db.rollback()
        logger.exception("Error ejecutando los procesos económicos periódicos")
    finally:
        db.close()


async def periodic_economy_loop() -> None:
    while True:
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)
        await asyncio.to_thread(run_once)
