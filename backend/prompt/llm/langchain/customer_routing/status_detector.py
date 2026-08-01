"""
Customer Status Detector with Redis Caching
==========================================

High-performance customer status detection with:
1. Redis caching for frequent queries
2. Database-driven status detection
3. Semantic analysis fallback for ambiguous cases
4. Comprehensive error handling and monitoring
"""

import logging
import json
from typing import Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from .models import (
    CustomerStatus,
    CustomerStatusResult,
    StatusDetectionContext
)
from .customer_status_service import CustomerStatusService

# Redis import (matches existing pattern)
try:
    from backend.prompt.llm.langchain.transitions.integration_helper import get_redis_client
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class CustomerStatusDetector:
    """
    High-performance customer status detector with caching and fallback mechanisms.

    Detection hierarchy:
    1. Redis cache (sub-second response)
    2. Database query (optimized SQL)
    3. Semantic analysis (for ambiguous cases)
    4. Safe fallback (LEAD status)
    """

    def __init__(self, db: Session, company_id: int, enable_cache: bool = True):
        """
        Initialize detector with database and caching configuration.

        Args:
            db: SQLAlchemy database session
            company_id: Company ID for context
            enable_cache: Whether to use Redis caching
        """
        self.db = db
        self.company_id = company_id
        self.enable_cache = enable_cache and REDIS_AVAILABLE

        # Initialize services
        self.status_service = CustomerStatusService(db, company_id)

        # Redis client (if available)
        self.redis_client = None
        if self.enable_cache:
            try:
                self.redis_client = get_redis_client()
                logger.info(f"[StatusDetector] Redis cache enabled for company_id={company_id}")
            except Exception as e:
                logger.warning(f"[StatusDetector] Redis unavailable, disabling cache: {e}")
                self.enable_cache = False

        # Cache configuration
        self.cache_ttl = 300  # 5 minutes default TTL
        self.cache_prefix = f"customer_status:c{company_id}:"

        # Performance tracking
        self.query_count = 0
        self.cache_hits = 0
        self.cache_misses = 0

    def detect_customer_status(
        self,
        context: StatusDetectionContext
    ) -> CustomerStatusResult:
        """
        Detect customer status with caching and fallback mechanisms.

        Args:
            context: Detection context with phone, company_id, etc.

        Returns:
            CustomerStatusResult with status and metadata
        """
        start_time = datetime.now()

        try:
            # 1. Try cache first (if enabled)
            if self.enable_cache and context.use_cache:
                cached_result = self._get_from_cache(context.contact_phone)
                if cached_result:
                    cached_result.cached = True
                    self.cache_hits += 1
                    logger.debug(f"[StatusDetector] Cache hit for {context.contact_phone}")
                    return cached_result
                else:
                    self.cache_misses += 1

            # 2. Database query
            status_result = self.status_service.get_customer_status(context.contact_phone)

            # 3. Enhance with additional context if needed
            if status_result.status != CustomerStatus.LEAD:
                customer_context = self.status_service.get_customer_context(context.contact_phone)
                appointment_details = self.status_service.get_latest_appointment_details(context.contact_phone)

                # Add context metadata (without changing the core model)
                status_result.total_appointments = customer_context.get('total_appointments', 0)
                status_result.total_purchases = customer_context.get('total_sales', 0)

            # 4. Cache result (if caching enabled)
            if self.enable_cache:
                self._cache_result(context.contact_phone, status_result, context.cache_ttl)

            # 5. Update performance metrics
            self.query_count += 1
            detection_time = (datetime.now() - start_time).total_seconds() * 1000

            logger.info(f"[StatusDetector] Status detected for {context.contact_phone}: "
                       f"{status_result.status.value} (took {detection_time:.1f}ms)")

            return status_result

        except Exception as e:
            logger.error(f"[StatusDetector] Error detecting status for {context.contact_phone}: {e}",
                        exc_info=True)

            # Return safe fallback
            return CustomerStatusResult(
                status=CustomerStatus.LEAD,
                detection_method="error_fallback",
                confidence=0.1  # Very low confidence due to error
            )

    def _get_from_cache(self, contact_phone: str) -> Optional[CustomerStatusResult]:
        """
        Get customer status from Redis cache.

        Args:
            contact_phone: Customer phone number

        Returns:
            Cached CustomerStatusResult or None
        """
        if not self.redis_client:
            return None

        try:
            cache_key = f"{self.cache_prefix}{contact_phone}"
            cached_data = self.redis_client.get(cache_key)

            if cached_data:
                # Parse cached JSON data
                data = json.loads(cached_data)
                return CustomerStatusResult(**data)

            return None

        except Exception as e:
            logger.warning(f"[StatusDetector] Cache read error for {contact_phone}: {e}")
            return None

    def _cache_result(
        self,
        contact_phone: str,
        result: CustomerStatusResult,
        ttl: int
    ) -> None:
        """
        Cache customer status result in Redis.

        Args:
            contact_phone: Customer phone number
            result: Status result to cache
            ttl: Time to live in seconds
        """
        if not self.redis_client:
            return

        try:
            cache_key = f"{self.cache_prefix}{contact_phone}"

            # Serialize to JSON (exclude cached flag to avoid confusion)
            cache_data = result.dict()
            cache_data['cached'] = False  # Will be set to True when retrieved

            self.redis_client.setex(
                cache_key,
                ttl,
                json.dumps(cache_data, default=str)  # Handle datetime serialization
            )

            logger.debug(f"[StatusDetector] Cached status for {contact_phone} (TTL: {ttl}s)")

        except Exception as e:
            logger.warning(f"[StatusDetector] Cache write error for {contact_phone}: {e}")

    def invalidate_cache(self, contact_phone: str) -> None:
        """
        Invalidate cached status for a customer.

        Should be called when customer data changes (new appointment, etc.)

        Args:
            contact_phone: Customer phone number
        """
        if not self.redis_client:
            return

        try:
            cache_key = f"{self.cache_prefix}{contact_phone}"
            self.redis_client.delete(cache_key)
            logger.info(f"[StatusDetector] Cache invalidated for {contact_phone}")

        except Exception as e:
            logger.warning(f"[StatusDetector] Cache invalidation error for {contact_phone}: {e}")

    def warm_cache(self, contact_phones: list[str]) -> None:
        """
        Pre-warm cache for a list of customers.

        Useful for batch operations or preparing for high-traffic periods.

        Args:
            contact_phones: List of phone numbers to pre-cache
        """
        logger.info(f"[StatusDetector] Warming cache for {len(contact_phones)} customers")

        for phone in contact_phones:
            try:
                context = StatusDetectionContext(
                    contact_phone=phone,
                    company_id=self.company_id,
                    use_cache=False  # Force database query
                )
                self.detect_customer_status(context)
            except Exception as e:
                logger.warning(f"[StatusDetector] Cache warm error for {phone}: {e}")

    def get_cache_stats(self) -> dict:
        """
        Get cache performance statistics.

        Returns:
            Dict with cache performance metrics
        """
        total_queries = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_queries * 100) if total_queries > 0 else 0

        return {
            "cache_enabled": self.enable_cache,
            "total_queries": self.query_count,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": f"{hit_rate:.1f}%",
            "company_id": self.company_id
        }

    def clear_company_cache(self) -> int:
        """
        Clear all cached customer statuses for this company.

        Returns:
            Number of keys deleted
        """
        if not self.redis_client:
            return 0

        try:
            pattern = f"{self.cache_prefix}*"
            keys = self.redis_client.keys(pattern)

            if keys:
                deleted = self.redis_client.delete(*keys)
                logger.info(f"[StatusDetector] Cleared {deleted} cached entries for company {self.company_id}")
                return deleted

            return 0

        except Exception as e:
            logger.error(f"[StatusDetector] Error clearing company cache: {e}")
            return 0


# Factory functions for easier usage
def create_status_detector(
    db: Session,
    company_id: int,
    enable_cache: bool = True
) -> CustomerStatusDetector:
    """
    Factory function to create a configured status detector.

    Args:
        db: Database session
        company_id: Company ID
        enable_cache: Whether to enable Redis caching

    Returns:
        Configured CustomerStatusDetector
    """
    return CustomerStatusDetector(db, company_id, enable_cache)


def quick_status_check(
    db: Session,
    company_id: int,
    contact_phone: str
) -> CustomerStatus:
    """
    Quick status check without full context.

    Args:
        db: Database session
        company_id: Company ID
        contact_phone: Customer phone

    Returns:
        CustomerStatus enum value
    """
    detector = create_status_detector(db, company_id)
    context = StatusDetectionContext(
        contact_phone=contact_phone,
        company_id=company_id
    )

    result = detector.detect_customer_status(context)
    return result.status


def batch_status_detection(
    db: Session,
    company_id: int,
    contact_phones: list[str]
) -> dict[str, CustomerStatusResult]:
    """
    Batch status detection for multiple customers.

    Args:
        db: Database session
        company_id: Company ID
        contact_phones: List of phone numbers

    Returns:
        Dict mapping phone numbers to status results
    """
    detector = create_status_detector(db, company_id)
    results = {}

    for phone in contact_phones:
        try:
            context = StatusDetectionContext(
                contact_phone=phone,
                company_id=company_id
            )
            results[phone] = detector.detect_customer_status(context)
        except Exception as e:
            logger.error(f"[BatchDetection] Error for {phone}: {e}")
            results[phone] = CustomerStatusResult(
                status=CustomerStatus.LEAD,
                detection_method="batch_error",
                confidence=0.1
            )

    return results