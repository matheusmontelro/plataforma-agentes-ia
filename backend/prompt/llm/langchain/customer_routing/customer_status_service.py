"""
Customer Status Service - Database Layer
=======================================

Service layer for querying customer status from database with optimized SQL queries.
Provides abstraction over database operations with proper error handling.
"""

import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import CustomerStatus, CustomerStatusResult

logger = logging.getLogger(__name__)


class CustomerStatusService:
    """
    Service class for customer status database operations.

    Provides optimized SQL queries to determine customer status based on:
    - Appointments (agendamentos)
    - Attendances (comparecimentos)
    - Sales (vendas)
    """

    def __init__(self, db: Session, company_id: int):
        """
        Initialize service with database session and company context.

        Args:
            db: SQLAlchemy database session
            company_id: Company ID for filtering queries
        """
        self.db = db
        self.company_id = company_id

    def get_customer_status(self, contact_phone: str) -> CustomerStatusResult:
        """
        Get comprehensive customer status with single optimized query.

        Uses hierarchical logic:
        1. PURCHASED - Has sales records
        2. ATTENDED - Has attendance records
        3. SCHEDULED - Has future appointments
        4. NO_SHOW - Has past appointments with NO_SHOW status
        5. LEAD - No appointment history

        Args:
            contact_phone: Customer phone number

        Returns:
            CustomerStatusResult with status and context
        """
        try:
            # Single query to get all customer data with CTEs for performance
            query = text("""
            WITH customer_appointments AS (
                SELECT
                    a.id as appointment_id,
                    a.status as appointment_status,
                    a.consulta_data,
                    a.nome,
                    a.interesse as tratamento,
                    ROW_NUMBER() OVER (ORDER BY a.consulta_data DESC) as rn_desc,
                    ROW_NUMBER() OVER (ORDER BY a.consulta_data ASC) as rn_asc,
                    CASE
                        WHEN a.consulta_data > CURRENT_TIMESTAMP THEN 'future'
                        ELSE 'past'
                    END as time_category
                FROM agendamentos a
                WHERE a.phone = :phone
                  AND a.company_id = :company_id
                  AND a.consulta_data > CURRENT_TIMESTAMP - INTERVAL '12 months'
            ),
            customer_attendances AS (
                SELECT
                    c.id as attendance_id,
                    c.agendamento_id,
                    c.compareceu_em,
                    c.tratamento_orcado,
                    c.valor_orcamento,
                    ROW_NUMBER() OVER (ORDER BY c.compareceu_em DESC) as rn
                FROM comparecimentos c
                INNER JOIN agendamentos a ON a.id = c.agendamento_id
                WHERE a.phone = :phone
                  AND a.company_id = :company_id
                  AND c.compareceu_em > CURRENT_TIMESTAMP - INTERVAL '12 months'
            ),
            customer_sales AS (
                SELECT
                    v.id as sale_id,
                    v.comparecimento_id,
                    v.venda_data,
                    v.tratamento_fechado,
                    v.valor_faturado,
                    v.valor_pago,
                    ROW_NUMBER() OVER (ORDER BY v.venda_data DESC) as rn
                FROM vendas v
                INNER JOIN comparecimentos c ON c.id = v.comparecimento_id
                INNER JOIN agendamentos a ON a.id = c.agendamento_id
                WHERE a.phone = :phone
                  AND a.company_id = :company_id
                  AND v.venda_data > CURRENT_TIMESTAMP - INTERVAL '12 months'
            ),
            customer_summary AS (
                SELECT
                    -- Latest sale info
                    ps.sale_id,
                    ps.venda_data as latest_sale_date,
                    ps.tratamento_fechado,
                    ps.valor_faturado,

                    -- Latest attendance info
                    pa.attendance_id,
                    pa.compareceu_em as latest_attendance_date,
                    pa.tratamento_orcado,
                    pa.valor_orcamento,

                    -- Latest appointment info
                    papp.appointment_id,
                    papp.appointment_status,
                    papp.consulta_data as latest_appointment_date,
                    papp.nome,
                    papp.tratamento,
                    papp.time_category,

                    -- Counts
                    (SELECT COUNT(*) FROM customer_appointments) as total_appointments,
                    (SELECT COUNT(*) FROM customer_attendances) as total_attendances,
                    (SELECT COUNT(*) FROM customer_sales) as total_sales,

                    -- Future appointments
                    (SELECT COUNT(*) FROM customer_appointments WHERE time_category = 'future') as future_appointments,
                    (SELECT COUNT(*) FROM customer_appointments WHERE time_category = 'past' AND appointment_status = 'NO_SHOW') as no_shows

                FROM customer_appointments papp
                LEFT JOIN customer_attendances pa ON pa.rn = 1
                LEFT JOIN customer_sales ps ON ps.rn = 1
                WHERE papp.rn_desc = 1

                UNION ALL

                -- Case where customer has attendances/sales but no appointments in timeframe
                SELECT
                    ps.sale_id,
                    ps.venda_data as latest_sale_date,
                    ps.tratamento_fechado,
                    ps.valor_faturado,

                    pa.attendance_id,
                    pa.compareceu_em as latest_attendance_date,
                    pa.tratamento_orcado,
                    pa.valor_orcamento,

                    NULL as appointment_id,
                    NULL as appointment_status,
                    pa.compareceu_em as latest_appointment_date,
                    NULL as nome,
                    pa.tratamento_orcado as tratamento,
                    'past' as time_category,

                    0 as total_appointments,
                    (SELECT COUNT(*) FROM customer_attendances) as total_attendances,
                    (SELECT COUNT(*) FROM customer_sales) as total_sales,
                    0 as future_appointments,
                    0 as no_shows

                FROM customer_attendances pa
                LEFT JOIN customer_sales ps ON ps.rn = 1
                WHERE pa.rn = 1
                  AND NOT EXISTS (SELECT 1 FROM customer_appointments)
            )
            SELECT * FROM customer_summary LIMIT 1
            """)

            result = self.db.execute(query, {
                "phone": contact_phone,
                "company_id": self.company_id
            }).fetchone()

            if not result:
                # No history found - this is a new lead
                return CustomerStatusResult(
                    status=CustomerStatus.LEAD,
                    detection_method="database_query",
                    confidence=1.0,
                    total_appointments=0,
                    total_purchases=0
                )

            # Determine status based on hierarchy
            status_data = self._determine_status_from_result(result)

            # Calculate additional context
            days_since_last = None
            if status_data['last_appointment']:
                days_since_last = (datetime.now() - status_data['last_appointment']).days

            return CustomerStatusResult(
                status=status_data['status'],
                last_appointment=status_data['last_appointment'],
                appointment_id=result.appointment_id,
                attendance_id=result.attendance_id,
                sale_id=result.sale_id,
                confidence=1.0,
                detection_method="database_query",
                days_since_last_appointment=days_since_last,
                total_appointments=result.total_appointments or 0,
                total_purchases=result.total_sales or 0
            )

        except Exception as e:
            logger.error(f"[CustomerStatusService] Error querying status for {contact_phone}: {e}", exc_info=True)
            # Return safe default
            return CustomerStatusResult(
                status=CustomerStatus.LEAD,
                detection_method="error_fallback",
                confidence=0.5
            )

    def _determine_status_from_result(self, result) -> Dict[str, Any]:
        """
        Determine customer status from query result using business logic hierarchy.

        Args:
            result: Database query result row

        Returns:
            Dict with status and last_appointment
        """
        # 1. PURCHASED - Highest priority
        if result.sale_id:
            return {
                'status': CustomerStatus.PURCHASED,
                'last_appointment': result.latest_sale_date or result.latest_appointment_date
            }

        # 2. ATTENDED - Second priority
        if result.attendance_id:
            return {
                'status': CustomerStatus.ATTENDED,
                'last_appointment': result.latest_attendance_date or result.latest_appointment_date
            }

        # 3. SCHEDULED - Has future appointments
        if result.future_appointments and result.future_appointments > 0:
            return {
                'status': CustomerStatus.SCHEDULED,
                'last_appointment': result.latest_appointment_date
            }

        # 4. NO_SHOW - Has past appointments marked as no-show
        if result.appointment_status == 'NO_SHOW':
            return {
                'status': CustomerStatus.NO_SHOW,
                'last_appointment': result.latest_appointment_date
            }

        # 5. Has appointments but none of the above - treat as attended (legacy data)
        if result.total_appointments and result.total_appointments > 0:
            return {
                'status': CustomerStatus.ATTENDED,
                'last_appointment': result.latest_appointment_date
            }

        # 6. LEAD - No significant history
        return {
            'status': CustomerStatus.LEAD,
            'last_appointment': None
        }

    def has_future_appointments(self, contact_phone: str) -> bool:
        """
        Quick check if customer has future scheduled appointments.

        Args:
            contact_phone: Customer phone number

        Returns:
            True if customer has future appointments
        """
        try:
            query = text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM agendamentos
                    WHERE phone = :phone
                      AND company_id = :company_id
                      AND consulta_data > CURRENT_TIMESTAMP
                )
            """)

            result = self.db.execute(query, {
                "phone": contact_phone,
                "company_id": self.company_id
            }).scalar()

            return result is True

        except Exception as e:
            logger.error(f"[CustomerStatusService] Error checking future appointments for {contact_phone}: {e}")
            return False

    def get_customer_context(self, contact_phone: str) -> Dict[str, Any]:
        """
        Get enriched customer context for prompt enhancement.

        Args:
            contact_phone: Customer phone number

        Returns:
            Dict with customer context data
        """
        try:
            query = text("""
            SELECT
                COUNT(DISTINCT a.id) as total_appointments,
                COUNT(DISTINCT c.id) as total_attendances,
                COUNT(DISTINCT v.id) as total_sales,
                MAX(a.consulta_data) as last_appointment_date,
                MAX(c.compareceu_em) as last_attendance_date,
                MAX(v.venda_data) as last_sale_date,
                COALESCE(SUM(v.valor_faturado), 0) as total_revenue,
                STRING_AGG(DISTINCT a.interesse, ', ') as treatments_discussed,
                AVG(CASE WHEN a.status = 'NO_SHOW' THEN 1.0 ELSE 0.0 END) as no_show_rate
            FROM agendamentos a
            LEFT JOIN comparecimentos c ON c.agendamento_id = a.id
            LEFT JOIN vendas v ON v.comparecimento_id = c.id
            WHERE a.phone = :phone
              AND a.company_id = :company_id
              AND a.consulta_data > CURRENT_TIMESTAMP - INTERVAL '12 months'
            """)

            result = self.db.execute(query, {
                "phone": contact_phone,
                "company_id": self.company_id
            }).fetchone()

            if not result or result.total_appointments == 0:
                return {
                    "is_new_customer": True,
                    "total_appointments": 0,
                    "total_attendances": 0,
                    "total_sales": 0,
                    "customer_value": "new",
                    "engagement_level": "new"
                }

            # Calculate engagement metrics
            attendance_rate = (result.total_attendances / result.total_appointments) if result.total_appointments > 0 else 0

            customer_value = "low"
            if result.total_sales > 0:
                if result.total_revenue > 5000:
                    customer_value = "high"
                elif result.total_revenue > 2000:
                    customer_value = "medium"
                else:
                    customer_value = "converting"
            elif result.total_attendances > 2:
                customer_value = "engaged"

            engagement_level = "low"
            if attendance_rate > 0.8:
                engagement_level = "high"
            elif attendance_rate > 0.5:
                engagement_level = "medium"

            return {
                "is_new_customer": False,
                "total_appointments": result.total_appointments,
                "total_attendances": result.total_attendances,
                "total_sales": result.total_sales,
                "total_revenue": float(result.total_revenue or 0),
                "attendance_rate": attendance_rate,
                "no_show_rate": float(result.no_show_rate or 0),
                "treatments_discussed": result.treatments_discussed,
                "last_appointment_date": result.last_appointment_date,
                "last_attendance_date": result.last_attendance_date,
                "last_sale_date": result.last_sale_date,
                "customer_value": customer_value,
                "engagement_level": engagement_level
            }

        except Exception as e:
            logger.error(f"[CustomerStatusService] Error getting customer context for {contact_phone}: {e}")
            return {
                "is_new_customer": True,
                "error": str(e)
            }

    def get_latest_appointment_details(self, contact_phone: str) -> Optional[Dict[str, Any]]:
        """
        Get details of the most recent appointment for context.

        Args:
            contact_phone: Customer phone number

        Returns:
            Dict with appointment details or None
        """
        try:
            query = text("""
            SELECT
                a.id,
                a.consulta_data,
                a.status,
                a.interesse as tratamento,
                a.nome,
                c.compareceu_em,
                c.tratamento_orcado,
                c.valor_orcamento,
                v.venda_data,
                v.tratamento_fechado,
                v.valor_faturado
            FROM agendamentos a
            LEFT JOIN comparecimentos c ON c.agendamento_id = a.id
            LEFT JOIN vendas v ON v.comparecimento_id = c.id
            WHERE a.phone = :phone
              AND a.company_id = :company_id
            ORDER BY a.consulta_data DESC
            LIMIT 1
            """)

            result = self.db.execute(query, {
                "phone": contact_phone,
                "company_id": self.company_id
            }).fetchone()

            if not result:
                return None

            return {
                "appointment_id": result.id,
                "appointment_date": result.consulta_data,
                "appointment_status": result.status,
                "treatment": result.tratamento,
                "customer_name": result.nome,
                "attended": result.compareceu_em is not None,
                "attendance_date": result.compareceu_em,
                "quoted_treatment": result.tratamento_orcado,
                "quoted_value": float(result.valor_orcamento or 0),
                "purchased": result.venda_data is not None,
                "sale_date": result.venda_data,
                "purchased_treatment": result.tratamento_fechado,
                "sale_value": float(result.valor_faturado or 0)
            }

        except Exception as e:
            logger.error(f"[CustomerStatusService] Error getting appointment details for {contact_phone}: {e}")
            return None