"""
Celery tasks for Agents SDK - Database-based scheduling
"""

import logging

from celery import shared_task
from sqlalchemy.orm import sessionmaker

# Import database engine
from backend.db import engine

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="agents_sdk.fetch_and_store_company_slots")
def fetch_and_store_company_slots(self, company_id: int):
    """
    Celery task to fetch slots from integrations and store in database

    Args:
        company_id: ID of the company to process

    Returns:
        dict: Task result with slots count and status
    """
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        logger.info(f"[AgentsSDK Celery] Starting slot fetch for company {company_id}")

        # Import with correct path after reorganization
        from backend.agents_sdk.services.database_scheduling_service import DatabaseSchedulingService

        # Create service instance
        service = DatabaseSchedulingService(db, company_id)

        # Fetch from integrations and store in database
        stored_count = service.fetch_and_store_availabilities()

        # Get final stats
        stats = service.get_slots_stats()

        result = {
            "status": "success",
            "company_id": company_id,
            "slots_stored": stored_count,
            "total_available": stats.get("available_slots", 0),
            "sources": list(stats.get("sources", {}).keys())
        }

        logger.info(f"[AgentsSDK Celery] Completed slot fetch for company {company_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"[AgentsSDK Celery] Error fetching slots for company {company_id}: {e}", exc_info=True)
        return {
            "status": "error",
            "company_id": company_id,
            "error": str(e)
        }

    finally:
        db.close()


@shared_task(bind=True, name="agents_sdk.cleanup_expired_slots")
def cleanup_expired_slots(self):
    """
    Celery task to cleanup expired slots from all companies

    Returns:
        dict: Cleanup result with count of removed slots
    """
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        logger.info("[AgentsSDK Celery] Starting expired slots cleanup")

        from backend.agents_sdk.tools.slots_service import SlotsService
        slots_service = SlotsService(db)

        # Cleanup all expired slots
        removed_count = slots_service.cleanup_expired_slots()

        result = {
            "status": "success",
            "expired_slots_removed": removed_count
        }

        logger.info(f"[AgentsSDK Celery] Completed expired slots cleanup: {result}")
        return result

    except Exception as e:
        logger.error(f"[AgentsSDK Celery] Error cleaning expired slots: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }

    finally:
        db.close()


@shared_task(bind=True, name="agents_sdk.refresh_all_companies_slots")
def refresh_all_companies_slots(self):
    """
    Celery task to refresh slots for all active companies

    Returns:
        dict: Results for all companies processed
    """
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        logger.info("[AgentsSDK Celery] Starting bulk company slots refresh")

        # Get all active companies that have agent configurations
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT DISTINCT company_id
            FROM agent_configurations
            WHERE company_id IS NOT NULL
        """)).fetchall()

        company_ids = [row.company_id for row in result]

        results = {
            "status": "success",
            "companies_processed": 0,
            "total_companies": len(company_ids),
            "results": {}
        }

        for company_id in company_ids:
            try:
                # Import and create service for each company
                from backend.agents_sdk.services.database_scheduling_service import DatabaseSchedulingService
                service = DatabaseSchedulingService(db, company_id)
                stored_count = service.fetch_and_store_availabilities()

                results["results"][company_id] = {
                    "status": "success",
                    "slots_stored": stored_count
                }
                results["companies_processed"] += 1

                logger.info(f"[AgentsSDK Celery] Processed company {company_id}: {stored_count} slots")

            except Exception as e:
                logger.error(f"[AgentsSDK Celery] Error processing company {company_id}: {e}")
                results["results"][company_id] = {
                    "status": "error",
                    "error": str(e)
                }

        logger.info(f"[AgentsSDK Celery] Completed bulk refresh: {results['companies_processed']}/{results['total_companies']} companies")
        return results

    except Exception as e:
        logger.error(f"[AgentsSDK Celery] Error in bulk company refresh: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }

    finally:
        db.close()


# Periodic task configuration (to be added to celerybeat schedule)
CELERYBEAT_SCHEDULE = {
    'refresh-company-slots': {
        'task': 'agents_sdk.refresh_all_companies_slots',
        'schedule': 300.0,  # Every 5 minutes
    },
    'cleanup-expired-slots': {
        'task': 'agents_sdk.cleanup_expired_slots',
        'schedule': 3600.0,  # Every hour
    },
}


@shared_task(bind=True, name="agents_sdk.populate_sample_slots")
def populate_sample_slots(self, company_id: int, days: int = 7):
    """
    Development task to populate sample slots for testing

    Args:
        company_id: ID of the company
        days: Number of days to create slots for

    Returns:
        dict: Result with count of created slots
    """
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        logger.info(f"[AgentsSDK Celery] Creating sample slots for company {company_id}")

        from backend.agents_sdk.tools.slots_service import SlotsService
        slots_service = SlotsService(db)

        created_count = slots_service.populate_sample_slots(company_id, days)

        result = {
            "status": "success",
            "company_id": company_id,
            "sample_slots_created": created_count
        }

        logger.info(f"[AgentsSDK Celery] Created sample slots for company {company_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"[AgentsSDK Celery] Error creating sample slots for company {company_id}: {e}")
        return {
            "status": "error",
            "company_id": company_id,
            "error": str(e)
        }

    finally:
        db.close()
