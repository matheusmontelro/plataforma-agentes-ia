"""
Action Validator - Validates Actions Against Customer Status
==========================================================

Comprehensive validation system that ensures actions requested by users
or detected in LLM responses are appropriate for the customer's status.
"""

import logging
import re
from typing import Dict, List, Set, Optional
from enum import Enum

from ..customer_routing.models import (
    CustomerStatus,
    ActionType,
    ValidationResult,
    AllowedActions,
    get_status_allowed_actions
)

logger = logging.getLogger(__name__)


class ValidationStrategy(str, Enum):
    """Validation strategies for different scenarios"""
    STRICT = "strict"        # Block any disallowed action
    PERMISSIVE = "permissive"  # Warn but allow with modifications
    CONTEXTUAL = "contextual"  # Consider context before blocking


class ActionValidator:
    """
    Validates actions against customer status with configurable strategies.

    Provides:
    - Intent detection from user input
    - Action validation against status rules
    - Contextual validation with business logic
    - Suggestion generation for alternative actions
    """

    def __init__(self, strategy: ValidationStrategy = ValidationStrategy.STRICT):
        """
        Initialize validator with strategy.

        Args:
            strategy: Validation strategy to use
        """
        self.strategy = strategy

        # Intent detection patterns
        self.intent_patterns = self._initialize_intent_patterns()

        # Status-specific allowed actions (cached)
        self._status_actions_cache = {}

        logger.info(f"[ActionValidator] Initialized with strategy: {strategy.value}")

    def _initialize_intent_patterns(self) -> Dict[ActionType, List[str]]:
        """Initialize regex patterns for intent detection"""
        return {
            ActionType.SCHEDULE_NEW: [
                r"agendar.*consulta",
                r"marcar.*horário",
                r"quero.*agendar",
                r"gostaria.*consulta",
                r"disponibilidade.*para",
                r"quando.*posso.*vir",
                r"primeira.*consulta",
                r"consulta.*inicial"
            ],

            ActionType.RESCHEDULE: [
                r"reagendar",
                r"mudar.*horário",
                r"trocar.*data",
                r"alterar.*consulta",
                r"remarcar",
                r"outro.*horário",
                r"não.*posso.*ir",
                r"imprevisto"
            ],

            ActionType.CANCEL: [
                r"cancelar.*consulta",
                r"desmarcar",
                r"não.*vou.*mais",
                r"desistir.*consulta",
                r"não.*quero.*mais",
                r"cancel[ae]r"
            ],

            ActionType.CONFIRM: [
                r"confirmar.*consulta",
                r"consulta.*confirmada",
                r"vou.*comparecer",
                r"estarei.*lá",
                r"confirmo.*presença",
                r"dados.*da.*consulta"
            ],

            ActionType.CLARIFY: [
                r"dúvida.*sobre",
                r"não.*entendi",
                r"pode.*explicar",
                r"como.*funciona",
                r"gostaria.*saber",
                r"informação.*sobre",
                r"esclarecer"
            ],

            ActionType.SUPPORT: [
                r"ajuda.*com",
                r"suporte.*para",
                r"orientação.*sobre",
                r"instrução.*para",
                r"como.*devo",
                r"preciso.*orientação"
            ],

            ActionType.OBJECTION_HANDLING: [
                r"muito.*caro",
                r"preço.*alto",
                r"não.*tenho.*dinheiro",
                r"muito.*doloroso",
                r"tenho.*medo",
                r"não.*confio",
                r"mudar.*de.*ideia"
            ]
        }

    def detect_user_intent(self, user_input: str) -> List[ActionType]:
        """
        Detect user intents from input text.

        Args:
            user_input: User's message text

        Returns:
            List of detected action types
        """
        detected_intents = []
        user_lower = user_input.lower()

        for action_type, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if re.search(pattern, user_lower):
                    detected_intents.append(action_type)
                    break  # Avoid duplicate detection for same action

        logger.debug(f"[ActionValidator] Detected intents: {detected_intents} from: '{user_input[:50]}...'")
        return detected_intents

    def validate_action(
        self,
        action: ActionType,
        customer_status: CustomerStatus,
        context: Optional[Dict] = None
    ) -> ValidationResult:
        """
        Validate if action is allowed for customer status.

        Args:
            action: Action to validate
            customer_status: Current customer status
            context: Optional context for validation

        Returns:
            ValidationResult with details
        """
        try:
            # Get allowed actions for status
            allowed_actions = self._get_allowed_actions(customer_status)

            # Check if action is directly allowed
            if action in allowed_actions.actions:
                return ValidationResult(
                    valid=True,
                    action=action,
                    customer_status=customer_status
                )

            # Apply strategy-specific validation
            if self.strategy == ValidationStrategy.STRICT:
                return self._strict_validation(action, customer_status, allowed_actions)
            elif self.strategy == ValidationStrategy.PERMISSIVE:
                return self._permissive_validation(action, customer_status, allowed_actions, context)
            elif self.strategy == ValidationStrategy.CONTEXTUAL:
                return self._contextual_validation(action, customer_status, allowed_actions, context)

            # Default to strict
            return self._strict_validation(action, customer_status, allowed_actions)

        except Exception as e:
            logger.error(f"[ActionValidator] Validation error: {e}")
            return ValidationResult(
                valid=False,
                action=action,
                customer_status=customer_status,
                reason=f"Validation error: {str(e)}"
            )

    def _get_allowed_actions(self, customer_status: CustomerStatus) -> AllowedActions:
        """Get allowed actions for status with caching"""
        if customer_status not in self._status_actions_cache:
            self._status_actions_cache[customer_status] = get_status_allowed_actions(customer_status)

        return self._status_actions_cache[customer_status]

    def _strict_validation(
        self,
        action: ActionType,
        customer_status: CustomerStatus,
        allowed_actions: AllowedActions
    ) -> ValidationResult:
        """Strict validation - block all disallowed actions"""

        reason = self._get_restriction_reason(action, customer_status)
        suggested_response = allowed_actions.get_restriction_message(action)

        return ValidationResult(
            valid=False,
            action=action,
            customer_status=customer_status,
            reason=reason,
            suggested_response=suggested_response,
            alternative_actions=allowed_actions.actions
        )

    def _permissive_validation(
        self,
        action: ActionType,
        customer_status: CustomerStatus,
        allowed_actions: AllowedActions,
        context: Optional[Dict] = None
    ) -> ValidationResult:
        """Permissive validation - allow with modifications"""

        # Check if action can be modified to be acceptable
        modified_action = self._try_modify_action(action, customer_status, context)

        if modified_action and modified_action in allowed_actions.actions:
            return ValidationResult(
                valid=True,
                action=modified_action,
                customer_status=customer_status,
                reason=f"Action modified from {action.value} to {modified_action.value}",
                suggested_response=f"Entendi sua solicitação. Posso ajudar com {modified_action.value}."
            )

        # Fall back to strict validation
        return self._strict_validation(action, customer_status, allowed_actions)

    def _contextual_validation(
        self,
        action: ActionType,
        customer_status: CustomerStatus,
        allowed_actions: AllowedActions,
        context: Optional[Dict] = None
    ) -> ValidationResult:
        """Contextual validation - consider business rules"""

        # Special contextual rules
        if action == ActionType.SCHEDULE_NEW and customer_status == CustomerStatus.NO_SHOW:
            # No-show customers might want to reschedule, not schedule new
            return ValidationResult(
                valid=True,  # Allow but redirect
                action=ActionType.RESCHEDULE,
                customer_status=customer_status,
                reason="Interpreted as reschedule request for no-show customer",
                suggested_response="Vejo que você teve uma consulta conosco. Gostaria de reagendar?"
            )

        if action == ActionType.SCHEDULE_NEW and customer_status in [CustomerStatus.ATTENDED, CustomerStatus.PURCHASED]:
            # Existing customers might want follow-up, not new consultation
            return ValidationResult(
                valid=False,
                action=action,
                customer_status=customer_status,
                reason="Existing customer requesting new appointment - may need follow-up instead",
                suggested_response="Como nosso cliente, você pode entrar em contato diretamente para retornos e acompanhamentos.",
                alternative_actions=[ActionType.CLARIFY, ActionType.SUPPORT]
            )

        # Fall back to strict validation
        return self._strict_validation(action, customer_status, allowed_actions)

    def _try_modify_action(
        self,
        action: ActionType,
        customer_status: CustomerStatus,
        context: Optional[Dict] = None
    ) -> Optional[ActionType]:
        """Try to modify action to make it acceptable"""

        modification_rules = {
            ActionType.SCHEDULE_NEW: {
                CustomerStatus.SCHEDULED: ActionType.RESCHEDULE,
                CustomerStatus.NO_SHOW: ActionType.RESCHEDULE,
                CustomerStatus.ATTENDED: ActionType.CLARIFY,
                CustomerStatus.PURCHASED: ActionType.SUPPORT
            },
            ActionType.RESCHEDULE: {
                CustomerStatus.ATTENDED: ActionType.CLARIFY,
                CustomerStatus.PURCHASED: ActionType.SUPPORT,
                CustomerStatus.LEAD: ActionType.SCHEDULE_NEW
            }
        }

        if action in modification_rules and customer_status in modification_rules[action]:
            return modification_rules[action][customer_status]

        return None

    def _get_restriction_reason(self, action: ActionType, customer_status: CustomerStatus) -> str:
        """Get specific reason for restriction"""

        reasons = {
            (ActionType.SCHEDULE_NEW, CustomerStatus.SCHEDULED):
                "Cliente já possui consulta agendada",
            (ActionType.SCHEDULE_NEW, CustomerStatus.NO_SHOW):
                "Cliente tem consulta perdida para reagendar",
            (ActionType.SCHEDULE_NEW, CustomerStatus.ATTENDED):
                "Cliente já passou por consulta - foque em suporte",
            (ActionType.SCHEDULE_NEW, CustomerStatus.PURCHASED):
                "Cliente já adquiriu tratamento - foque em suporte pós-venda",

            (ActionType.RESCHEDULE, CustomerStatus.ATTENDED):
                "Cliente já compareceu - não há consulta para reagendar",
            (ActionType.RESCHEDULE, CustomerStatus.PURCHASED):
                "Cliente já adquiriu tratamento - não há consulta para reagendar",
            (ActionType.RESCHEDULE, CustomerStatus.LEAD):
                "Lead não possui consulta para reagendar",

            (ActionType.CANCEL, CustomerStatus.ATTENDED):
                "Cliente já compareceu - não há consulta para cancelar",
            (ActionType.CANCEL, CustomerStatus.PURCHASED):
                "Cliente já adquiriu tratamento - não há consulta para cancelar",
            (ActionType.CANCEL, CustomerStatus.LEAD):
                "Lead não possui consulta para cancelar"
        }

        return reasons.get(
            (action, customer_status),
            f"Ação {action.value} não permitida para status {customer_status.value}"
        )

    def validate_user_input(
        self,
        user_input: str,
        customer_status: CustomerStatus,
        context: Optional[Dict] = None
    ) -> List[ValidationResult]:
        """
        Validate all detected intents in user input.

        Args:
            user_input: User's message
            customer_status: Current customer status
            context: Optional context

        Returns:
            List of validation results for each detected intent
        """
        detected_intents = self.detect_user_intent(user_input)

        if not detected_intents:
            # No specific intents detected - assume clarification request
            detected_intents = [ActionType.CLARIFY]

        results = []
        for intent in detected_intents:
            validation = self.validate_action(intent, customer_status, context)
            results.append(validation)

        return results

    def get_validation_summary(self, results: List[ValidationResult]) -> Dict:
        """
        Get summary of validation results.

        Args:
            results: List of validation results

        Returns:
            Summary dictionary
        """
        valid_actions = [r.action for r in results if r.valid]
        invalid_actions = [r.action for r in results if not r.valid]

        return {
            "total_intents": len(results),
            "valid_actions": valid_actions,
            "invalid_actions": invalid_actions,
            "has_valid_actions": len(valid_actions) > 0,
            "has_invalid_actions": len(invalid_actions) > 0,
            "primary_restriction": results[0].reason if results and not results[0].valid else None,
            "suggested_alternatives": list(set(
                action for result in results
                for action in (result.alternative_actions or [])
            ))
        }

    def get_validator_stats(self) -> Dict:
        """Get validator performance statistics"""
        return {
            "strategy": self.strategy.value,
            "intent_patterns_loaded": {
                action.value: len(patterns)
                for action, patterns in self.intent_patterns.items()
            },
            "cached_status_rules": len(self._status_actions_cache)
        }