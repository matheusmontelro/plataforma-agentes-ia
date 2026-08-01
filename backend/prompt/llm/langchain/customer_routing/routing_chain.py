"""
Customer Routing Chain - Main Orchestrator
=========================================

Main routing chain that:
1. Detects customer status from database
2. Selects appropriate specialized chain
3. Validates actions and responses
4. Provides comprehensive execution results
"""

import logging
from typing import Dict, Any, Optional, ClassVar, List
from datetime import datetime
from sqlalchemy.orm import Session

from langchain.chains.base import Chain
from pydantic import ConfigDict, Field

from .models import (
    CustomerStatus,
    CustomerStatusResult,
    StatusDetectionContext,
    RoutingResult,
    ChainExecutionResult,
    create_routing_context,
    get_status_allowed_actions
)
from .status_detector import CustomerStatusDetector

# Import all status-specific chains
from ..status_chains import (
    ScheduledCustomerChain,
    AttendedCustomerChain,
    PurchasedCustomerChain,
    LeadCustomerChain
)

# Import validation system
from ..restrictions import ActionValidator, ValidationResult, ValidationStrategy

logger = logging.getLogger(__name__)


class CustomerRoutingChain(Chain):
    """
    Main routing chain that orchestrates customer status detection and
    delegates to appropriate specialized chains.

    This is the entry point for the new customer routing system.
    """

    input_keys: ClassVar[List[str]] = ["contact_phone", "user_input", "conversation_history", "company_id"]
    output_keys: ClassVar[List[str]] = ["response", "routing_result", "execution_result"]

    # Declare Pydantic fields for attributes that need to be set
    db: Session = Field(default=None, exclude=True)
    company_id: int = Field(default=0)
    enable_cache: bool = Field(default=True)
    validation_strategy: ValidationStrategy = Field(default=ValidationStrategy.CONTEXTUAL)
    enable_response_filtering: bool = Field(default=True)
    status_detector: Optional[Any] = Field(default=None, exclude=True)
    action_validator: Optional[Any] = Field(default=None, exclude=True)
    status_chains: Dict[CustomerStatus, Any] = Field(default_factory=dict, exclude=True)
    routing_count: int = Field(default=0, exclude=True)
    routing_times: List[float] = Field(default_factory=list, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
        self,
        db: Session,
        company_id: int,
        enable_cache: bool = True,
        validation_strategy: ValidationStrategy = ValidationStrategy.CONTEXTUAL,
        enable_response_filtering: bool = True
    ):
        """
        Initialize routing chain with all components.

        Args:
            db: Database session
            company_id: Company ID for context
            enable_cache: Whether to enable Redis caching
            validation_strategy: Action validation strategy
            enable_response_filtering: Whether to filter responses
        """
        super().__init__()

        self.db = db
        self.company_id = company_id
        self.enable_cache = enable_cache
        self.validation_strategy = validation_strategy
        self.enable_response_filtering = enable_response_filtering

        # Initialize status detector
        self.status_detector = CustomerStatusDetector(
            db=db,
            company_id=company_id,
            enable_cache=enable_cache
        )

        # Initialize action validator
        self.action_validator = ActionValidator(strategy=validation_strategy)

        # Initialize status-specific chains
        self.status_chains = {
            CustomerStatus.SCHEDULED: ScheduledCustomerChain(
                db=db,
                company_id=company_id,
                enable_response_filtering=enable_response_filtering
            ),
            CustomerStatus.NO_SHOW: ScheduledCustomerChain(  # Same chain as SCHEDULED
                db=db,
                company_id=company_id,
                enable_response_filtering=enable_response_filtering
            ),
            CustomerStatus.ATTENDED: AttendedCustomerChain(
                db=db,
                company_id=company_id,
                enable_response_filtering=enable_response_filtering
            ),
            CustomerStatus.PURCHASED: PurchasedCustomerChain(
                db=db,
                company_id=company_id,
                enable_response_filtering=enable_response_filtering
            ),
            CustomerStatus.LEAD: LeadCustomerChain(
                db=db,
                company_id=company_id,
                enable_response_filtering=enable_response_filtering
            )
        }

        # Performance tracking
        self.routing_count = 0
        self.routing_times = []

        logger.info(f"[CustomerRoutingChain] Initialized for company_id={company_id}")

    def _call(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main routing logic - detect status and delegate to appropriate chain.

        Args:
            inputs: Chain inputs with contact_phone, user_input, etc.

        Returns:
            Dict with response and routing metadata
        """
        start_time = datetime.now()

        try:
            # Extract inputs
            contact_phone = inputs.get("contact_phone", "")
            user_input = inputs.get("user_input", "")
            conversation_history = inputs.get("conversation_history", [])

            # Validate inputs
            if not contact_phone:
                raise ValueError("contact_phone is required")

            # 1. DETECT CUSTOMER STATUS
            detection_context = create_routing_context(
                contact_phone=contact_phone,
                company_id=self.company_id,
                user_input=user_input,
                conversation_history=conversation_history
            )

            customer_status = self.status_detector.detect_customer_status(detection_context)

            logger.info(f"[RoutingChain] Detected status: {customer_status.status.value} for {contact_phone}")

            # 2. VALIDATE USER ACTIONS (if any detected)
            validation_results = self.action_validator.validate_user_input(
                user_input,
                customer_status.status,
                context={"customer_data": customer_status.dict()}
            )

            # 3. GET ALLOWED ACTIONS FOR STATUS
            allowed_actions = get_status_allowed_actions(customer_status.status)

            # 4. SELECT AND EXECUTE APPROPRIATE CHAIN
            selected_chain = self.status_chains[customer_status.status]

            # Prepare chain inputs
            chain_inputs = {
                "user_input": user_input,
                "conversation_history": conversation_history,
                "customer_status": customer_status,
                "allowed_actions": allowed_actions,
                "validation_results": validation_results
            }

            # Execute chain
            chain_result = selected_chain(chain_inputs)

            # 5. CREATE ROUTING RESULT
            routing_time = (datetime.now() - start_time).total_seconds() * 1000

            routing_result = RoutingResult(
                selected_chain=selected_chain.__class__.__name__,
                customer_status=customer_status,
                allowed_actions=allowed_actions,
                routing_time_ms=routing_time,
                cache_hit=customer_status.cached,
                chain_context=chain_inputs,
                restrictions_applied=self._get_applied_restrictions(validation_results)
            )

            # 6. UPDATE PERFORMANCE METRICS
            self.routing_count += 1
            self.routing_times.append(routing_time)

            # Keep only last 100 routing times for stats
            if len(self.routing_times) > 100:
                self.routing_times = self.routing_times[-100:]

            logger.info(f"[RoutingChain] Completed routing in {routing_time:.1f}ms - "
                       f"Chain: {selected_chain.__class__.__name__}")

            return {
                "response": chain_result.get("response", ""),
                "routing_result": routing_result,
                "execution_result": chain_result.get("execution_result")
            }

        except Exception as e:
            logger.error(f"[RoutingChain] Routing error for {contact_phone}: {e}", exc_info=True)

            # Return safe fallback
            error_response = self._get_error_response(str(e))

            # Create error routing result
            error_routing_result = RoutingResult(
                selected_chain="ErrorFallback",
                customer_status=CustomerStatusResult(
                    status=CustomerStatus.LEAD,  # Safe default
                    detection_method="error_fallback",
                    confidence=0.1
                ),
                allowed_actions=get_status_allowed_actions(CustomerStatus.LEAD),
                routing_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                cache_hit=False,
                restrictions_applied=[f"Error: {str(e)}"]
            )

            return {
                "response": error_response,
                "routing_result": error_routing_result,
                "execution_result": None
            }

    def _get_applied_restrictions(self, validation_results) -> list[str]:
        """Extract applied restrictions from validation results"""
        restrictions = []

        for result in validation_results:
            if not result.valid and result.reason:
                restrictions.append(result.reason)

        return restrictions

    def _get_error_response(self, error_message: str) -> str:
        """Get user-friendly error response"""
        return ("Peço desculpas, mas estou enfrentando uma dificuldade técnica no momento. "
                "Poderia repetir sua solicitação ou entrar em contato diretamente conosco? "
                "Estou aqui para ajudar assim que possível!")

    def get_routing_stats(self) -> Dict[str, Any]:
        """Get routing performance statistics"""
        avg_routing_time = sum(self.routing_times) / len(self.routing_times) if self.routing_times else 0

        # Get status detector stats
        detector_stats = self.status_detector.get_cache_stats()

        # Get validator stats
        validator_stats = self.action_validator.get_validator_stats()

        return {
            "routing_count": self.routing_count,
            "average_routing_time_ms": round(avg_routing_time, 2),
            "min_routing_time_ms": min(self.routing_times) if self.routing_times else 0,
            "max_routing_time_ms": max(self.routing_times) if self.routing_times else 0,
            "company_id": self.company_id,
            "cache_enabled": self.enable_cache,
            "validation_strategy": self.validation_strategy.value,
            "detector_stats": detector_stats,
            "validator_stats": validator_stats,
            "available_chains": list(self.status_chains.keys())
        }

    def invalidate_customer_cache(self, contact_phone: str) -> None:
        """
        Invalidate cached customer status.

        Should be called when customer data changes.

        Args:
            contact_phone: Customer phone number
        """
        self.status_detector.invalidate_cache(contact_phone)
        logger.info(f"[RoutingChain] Cache invalidated for {contact_phone}")

    def warm_cache_for_customers(self, contact_phones: list[str]) -> None:
        """
        Pre-warm cache for multiple customers.

        Args:
            contact_phones: List of phone numbers to cache
        """
        self.status_detector.warm_cache(contact_phones)
        logger.info(f"[RoutingChain] Cache warmed for {len(contact_phones)} customers")

    def test_routing_for_status(
        self,
        status: CustomerStatus,
        test_input: str = "Olá, como está?"
    ) -> Dict[str, Any]:
        """
        Test routing for a specific status (for debugging/testing).

        Args:
            status: Customer status to test
            test_input: Test input message

        Returns:
            Test results
        """
        # Create mock customer status
        mock_customer_status = CustomerStatusResult(
            status=status,
            detection_method="test_mock",
            confidence=1.0
        )

        # Get appropriate chain
        selected_chain = self.status_chains[status]
        allowed_actions = get_status_allowed_actions(status)

        # Test chain inputs
        chain_inputs = {
            "user_input": test_input,
            "conversation_history": [],
            "customer_status": mock_customer_status,
            "allowed_actions": allowed_actions
        }

        try:
            # Execute chain
            start_time = datetime.now()
            result = selected_chain(chain_inputs)
            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            return {
                "status": status.value,
                "chain": selected_chain.__class__.__name__,
                "test_input": test_input,
                "response": result.get("response", ""),
                "execution_time_ms": execution_time,
                "allowed_actions": [action.value for action in allowed_actions.actions],
                "success": True
            }

        except Exception as e:
            return {
                "status": status.value,
                "chain": selected_chain.__class__.__name__,
                "test_input": test_input,
                "error": str(e),
                "success": False
            }


# Factory functions for easier usage
def create_customer_routing_chain(
    db: Session,
    company_id: int,
    enable_cache: bool = True,
    validation_strategy: ValidationStrategy = ValidationStrategy.CONTEXTUAL
) -> CustomerRoutingChain:
    """
    Factory function to create a configured customer routing chain.

    Args:
        db: Database session
        company_id: Company ID
        enable_cache: Whether to enable caching
        validation_strategy: Validation strategy to use

    Returns:
        Configured CustomerRoutingChain
    """
    return CustomerRoutingChain(
        db=db,
        company_id=company_id,
        enable_cache=enable_cache,
        validation_strategy=validation_strategy
    )


def quick_customer_response(
    db: Session,
    company_id: int,
    contact_phone: str,
    user_input: str,
    conversation_history: Optional[list] = None
) -> str:
    """
    Quick response generation without full routing metadata.

    Args:
        db: Database session
        company_id: Company ID
        contact_phone: Customer phone
        user_input: User message
        conversation_history: Optional conversation history

    Returns:
        Generated response string
    """
    routing_chain = create_customer_routing_chain(db, company_id)

    result = routing_chain({
        "contact_phone": contact_phone,
        "user_input": user_input,
        "conversation_history": conversation_history or [],
        "company_id": company_id
    })

    return result["response"]