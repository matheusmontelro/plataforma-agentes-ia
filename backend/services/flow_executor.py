"""
Flow Executor Service

Main engine for executing FlowBuilder flows in the backend.
Handles node traversal, variable resolution, and action execution.
"""

import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from collections import deque
from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend.models import Flow, FlowEnrollment, FlowStepExecution
from backend.services.flow_trigger_mapping import (
    merge_standard_fields_into_trigger,
    resolve_standard_webhook_fields,
)
from backend.services.company_access_control import (
    enqueue_company_job_if_active,
    fence_company_job_mutation,
)

logger = logging.getLogger(__name__)


class FlowExecutor:
    """
    Executes FlowBuilder flows in the backend.

    Supports:
    - Webhook triggers
    - WhatsApp message triggers
    - All node types (SendMessage, CreateLead, AgentResponse, etc.)
    - Variable interpolation between nodes
    """

    def __init__(
        self,
        flow_id: int,
        company_id: int,
        trigger_data: Dict[str, Any],
        trigger_type: str = 'webhook',
        enrollment_id: Optional[int] = None
    ):
        self.flow_id = flow_id
        self.company_id = company_id
        self.trigger_data = trigger_data
        self.trigger_type = trigger_type
        self.enrollment_id = enrollment_id
        self.expected_operational_epoch = trigger_data.get("_operational_epoch")

        # Flow state
        self.flow: Optional[Flow] = None
        self.nodes: List[Dict] = []
        self.edges: List[Dict] = []

        # Execution state
        self.variables: Dict[str, Any] = {}
        self.execution_log: List[Dict] = []
        self.nodes_executed: int = 0

        # Node handlers (lazy loaded)
        self._handlers = None

    def execute(self) -> Dict[str, Any]:
        """
        Execute the complete flow from its trigger node.

        Returns:
            Dict with:
            - success: bool
            - nodes_executed: int
            - execution_log: list
            - variables: dict (final variable state)
            - error: str (if failed)
        """
        db = SessionLocal()

        try:
            from backend.services.company_access_control import validate_company_job_epoch
            if (
                self.expected_operational_epoch is not None
                and not validate_company_job_epoch(
                    db,
                    self.company_id,
                    self.expected_operational_epoch,
                )
            ):
                return {
                    "success": False,
                    "error": "company_access_epoch_invalid",
                    "nodes_executed": 0,
                    "execution_log": [],
                }
            from backend.services.company_access_control import is_company_operational
            if not is_company_operational(db, self.company_id):
                return {
                    "success": False,
                    "error": "company_access_suspended",
                    "nodes_executed": 0,
                    "execution_log": [],
                }

            # 1. Load flow from database
            self._load_flow(db)
            self._load_enrollment_variables(db)

            if not self.flow:
                return {
                    "success": False,
                    "error": f"Flow {self.flow_id} not found",
                    "nodes_executed": 0,
                    "execution_log": []
                }

            if not self.flow.is_active:
                logger.warning(f"[FlowExecutor] Flow {self.flow_id} is not active, skipping execution")
                return {
                    "success": False,
                    "error": "Flow is not active",
                    "nodes_executed": 0,
                    "execution_log": []
                }

            # 2. Initialize variables from trigger
            self._init_trigger_variables()

            # 3. Find start node (trigger node)
            start_node = self._find_start_node()

            if not start_node:
                return {
                    "success": False,
                    "error": "No trigger node found in flow",
                    "nodes_executed": 0,
                    "execution_log": []
                }

            # 4. Execute node chain using BFS
            self._execute_chain(db, start_node)

            failed_nodes = [
                entry for entry in self.execution_log
                if not entry.get("success", False)
            ]
            first_error = None
            if failed_nodes:
                failed_result = failed_nodes[0].get("result") or {}
                first_error = failed_nodes[0].get("error") or failed_result.get("error") or "Flow node failed"

            logger.info(
                f"[FlowExecutor] Flow {self.flow_id} execution complete. "
                f"Nodes executed: {self.nodes_executed}, failed_nodes={len(failed_nodes)}"
            )

            return {
                "success": len(failed_nodes) == 0,
                "nodes_executed": self.nodes_executed,
                "execution_log": self.execution_log,
                "variables": self.variables,
                "error": first_error
            }

        except Exception as e:
            logger.exception(f"[FlowExecutor] Error executing flow {self.flow_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "nodes_executed": self.nodes_executed,
                "execution_log": self.execution_log
            }
        finally:
            db.close()

    def execute_from_node(
        self,
        node_id: str,
        initial_variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resume flow execution from a specific node.
        Used for delayed node execution.

        Args:
            node_id: ID of the node to start from
            initial_variables: Variables state to restore

        Returns:
            Execution result dict
        """
        db = SessionLocal()

        try:
            self._load_flow(db)
            self.variables = initial_variables
            self._load_enrollment_variables(db)

            # Find the specific node
            node = self._get_node_by_id(node_id)

            if not node:
                return {
                    "success": False,
                    "error": f"Node {node_id} not found",
                    "nodes_executed": 0
                }

            # Execute from this node
            self._execute_chain(db, node)

            return {
                "success": True,
                "nodes_executed": self.nodes_executed,
                "execution_log": self.execution_log,
                "variables": self.variables
            }

        finally:
            db.close()

    def _load_flow(self, db: Session):
        """Load flow from database"""
        self.flow = db.query(Flow).filter(
            Flow.id == self.flow_id,
            Flow.company_id == self.company_id
        ).first()

        if self.flow:
            self.nodes = self.flow.nodes or []
            self.edges = self.flow.edges or []
            logger.info(
                f"[FlowExecutor] Loaded flow {self.flow_id}: "
                f"{len(self.nodes)} nodes, {len(self.edges)} edges"
            )

    def _load_enrollment_variables(self, db: Session):
        """Attach persisted business-event context without affecting legacy flows."""
        if not self.enrollment_id:
            return

        enrollment = db.query(FlowEnrollment).filter(
            FlowEnrollment.id == self.enrollment_id,
            FlowEnrollment.flow_id == self.flow_id,
            FlowEnrollment.company_id == self.company_id,
        ).first()
        if not enrollment:
            logger.warning("[FlowExecutor] Enrollment %s not found", self.enrollment_id)
            return

        self.variables["flow_enrollment_id"] = enrollment.id
        self.variables["flow_enrollment"] = {
            "id": enrollment.id,
            "status": enrollment.status,
            "trigger_type": enrollment.trigger_type,
            "lead_id": enrollment.lead_id,
            "appointment_id": enrollment.appointment_id,
            "pipeline_id": enrollment.pipeline_id,
            "stage_id": enrollment.stage_id,
            "anchor_at": enrollment.anchor_at.isoformat() if enrollment.anchor_at else None,
        }
        if enrollment.anchor_at:
            self.variables["anchor_at"] = enrollment.anchor_at.isoformat()

    def _normalize_field_key(self, value: str) -> str:
        """Normalize dynamic field names to stable snake_case keys."""
        if not isinstance(value, str):
            return ""

        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
        ascii_value = re.sub(r"[^a-z0-9]+", "_", ascii_value)
        ascii_value = re.sub(r"_+", "_", ascii_value).strip("_")
        return ascii_value

    def _extract_trigger_fields(self, trigger_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a dictionary of lead form fields from Meta `field_data`.

        The output includes both original keys and normalized keys so flows can
        safely use templates like `{{trigger.fields.my_field_key}}`.
        """
        field_data = trigger_payload.get("field_data")
        if not isinstance(field_data, list):
            body = trigger_payload.get("body")
            if isinstance(body, dict):
                field_data = body.get("field_data")

        if not isinstance(field_data, list):
            return {}

        fields: Dict[str, Any] = {}
        for item in field_data:
            if not isinstance(item, dict):
                continue

            raw_name = str(item.get("name") or "").strip()
            if not raw_name:
                continue

            raw_values = item.get("values")
            if isinstance(raw_values, list):
                raw_value = raw_values[0] if raw_values else ""
            elif raw_values is None:
                raw_value = ""
            else:
                raw_value = raw_values

            value = str(raw_value).strip() if raw_value is not None else ""
            fields[raw_name] = value

            normalized_key = self._normalize_field_key(raw_name)
            if normalized_key:
                fields[normalized_key] = value

        return fields

    def _init_trigger_variables(self):
        """Initialize variables from trigger data"""

        trigger_payload = self.trigger_data.copy()
        existing_body = trigger_payload.get("body")
        if isinstance(existing_body, dict):
            trigger_payload["body"] = existing_body.copy()
        elif self.trigger_type == "webhook" and ("body" not in trigger_payload or existing_body is None):
            # Keep webhook runtime compatible with the FlowBuilder Run Once listener.
            trigger_payload["body"] = {
                key: value
                for key, value in trigger_payload.items()
                if key != "body"
            }

        standard_fields: Dict[str, Dict[str, Any]] = resolve_standard_webhook_fields(
            trigger_payload,
            self.flow.trigger_config if self.flow and self.trigger_type == "webhook" else {},
            self.company_id,
        )
        merge_standard_fields_into_trigger(trigger_payload, standard_fields)

        trigger_fields = self._extract_trigger_fields(trigger_payload)
        if trigger_fields:
            trigger_payload["fields"] = trigger_fields
            if isinstance(trigger_payload.get("body"), dict):
                trigger_payload["body"]["fields"] = trigger_fields

        # Standard trigger variables
        self.variables['trigger'] = trigger_payload

        # Flatten common fields for easy access
        if 'phone' in trigger_payload:
            self.variables['phone'] = trigger_payload['phone']
        elif 'whatsapp' in trigger_payload:
            # Typebot/webhook payloads often use "whatsapp" instead of "phone".
            self.variables['phone'] = trigger_payload['whatsapp']
        if 'whatsapp' in trigger_payload:
            self.variables['whatsapp'] = trigger_payload['whatsapp']
        if 'name' in trigger_payload:
            self.variables['name'] = trigger_payload['name']
            # Add first_name for personalization
            if trigger_payload['name']:
                # Get first part of name
                self.variables['first_name'] = trigger_payload['name'].split()[0]

        if 'email' in trigger_payload:
            self.variables['email'] = trigger_payload['email']
        if 'message' in trigger_payload:
            self.variables['message'] = trigger_payload['message']
        if 'body' in trigger_payload:
            self.variables['body'] = trigger_payload['body']
        if trigger_fields:
            self.variables['fields'] = trigger_fields
        for standard_key in ("lead", "company"):
            standard_value = trigger_payload.get(standard_key)
            if isinstance(standard_value, dict) and standard_value:
                self.variables[standard_key] = standard_value
        event_data = trigger_payload.get("event_data")
        if isinstance(event_data, dict) and event_data:
            self.variables["event_data"] = event_data
            if event_data.get("type") is not None:
                self.variables["event_type"] = event_data.get("type")
        for common_key in ("anchor_at", "appointment_id", "lead_id", "event"):
            if common_key in trigger_payload:
                self.variables[common_key] = trigger_payload[common_key]
        lead_data = self.variables.get("lead") if isinstance(self.variables.get("lead"), dict) else {}
        if "phone" not in self.variables and lead_data.get("phone"):
            self.variables["phone"] = lead_data["phone"]
        if "name" not in self.variables and lead_data.get("name"):
            self.variables["name"] = lead_data["name"]
        if "email" not in self.variables and lead_data.get("email"):
            self.variables["email"] = lead_data["email"]
        if "lead_id" not in self.variables and lead_data.get("id"):
            self.variables["lead_id"] = lead_data["id"]

        # For webhook triggers, flatten all payload fields AND nested body
        if self.trigger_type == 'webhook':
            for key, value in trigger_payload.items():
                if key not in self.variables:
                    self.variables[key] = value

            # Also try to populate from 'body' if it exists (common webhook structure)
            if 'body' in trigger_payload and isinstance(trigger_payload['body'], dict):
                for key, value in trigger_payload['body'].items():
                    if key not in self.variables:
                        self.variables[f"body.{key}"] = value # flatten body.key

        logger.debug(f"[FlowExecutor] Initialized variables: {list(self.variables.keys())}")

    def _find_start_node(self) -> Optional[Dict]:
        """Find the trigger/start node of the flow"""

        trigger_types = ['webhookTrigger', 'webhookNode', 'whatsappTrigger', 'appointmentTrigger', 'crmStageTrigger']

        for node in self.nodes:
            if node.get('type') in trigger_types:
                logger.info(f"[FlowExecutor] Found start node: {node.get('id')} ({node.get('type')})")
                return node

        return None

    def _get_node_by_id(self, node_id: str) -> Optional[Dict]:
        """Get a node by its ID"""
        for node in self.nodes:
            if node.get('id') == node_id:
                return node
        return None

    def _get_next_nodes(self, node_id: str) -> List[Dict]:
        """Get nodes connected to the output of the given node"""
        next_nodes = []

        for edge in self.edges:
            if edge.get('source') == node_id:
                target_id = edge.get('target')
                target_node = self._get_node_by_id(target_id)
                if target_node:
                    next_nodes.append(target_node)

        return next_nodes

    def _execute_chain(self, db: Session, start_node: Dict):
        """
        Execute the chain of nodes using BFS traversal.

        Args:
            db: Database session
            start_node: The node to start execution from
        """
        from backend.services.flow_node_handlers import get_node_handler
        from backend.services.company_access_control import (
            CompanyOperationallyBlockedError,
            ensure_company_operational,
            get_company_operational_epoch,
            lock_entities_for_mutation,
        )

        # BFS queue
        queue = deque([start_node])
        visited = set()

        while queue:
            node = queue.popleft()
            node_id = node.get('id')

            # Skip if already visited (prevents cycles)
            if node_id in visited:
                continue
            visited.add(node_id)

            node_type = node.get('type')
            node_data = node.get('data', {})

            logger.info(f"[FlowExecutor] Executing node: {node_id} ({node_type})")

            # Company state can change after the flow is loaded. Reacquire the
            # entity lock and revalidate before each node.
            try:
                lock_entities_for_mutation(
                    db,
                    company_ids=[self.company_id],
                )
                ensure_company_operational(db, self.company_id)
                if (
                    self.expected_operational_epoch is not None
                    and get_company_operational_epoch(db, self.company_id)
                    != int(self.expected_operational_epoch)
                ):
                    raise CompanyOperationallyBlockedError(
                        self.company_id,
                        "stale_operational_epoch",
                    )
            except CompanyOperationallyBlockedError:
                logger.warning(
                    "[FlowExecutor] Company %s suspended before node %s",
                    self.company_id,
                    node_id,
                )
                self.execution_log.append({
                    "node_id": node_id,
                    "node_type": node_type,
                    "success": False,
                    "error": "company_access_suspended",
                    "result": {
                        "success": False,
                        "error": "company_access_suspended",
                        "stop_flow": True,
                    },
                })
                break

            # Get handler for this node type
            handler = get_node_handler(node_type)

            if handler:
                try:
                    # Execute the node
                    result = handler.execute(
                        db=db,
                        node_data=node_data,
                        variables=self.variables,
                        company_id=self.company_id,
                        flow_id=self.flow_id
                    )

                    # Store result in variables
                    self.variables[f'nodes.{node_id}'] = result
                    self.variables[node_id] = result  # Also exposed at root for direct access {{nodeId...}}

                    # Log execution
                    self.execution_log.append({
                        "node_id": node_id,
                        "node_type": node_type,
                        "success": result.get('success', False),
                        "result": result
                    })

                    self.nodes_executed += 1

                    logger.info(
                        f"[FlowExecutor] Node {node_id} executed: "
                        f"success={result.get('success', False)}"
                    )

                    # Check if we should continue (some nodes might stop the flow)
                    if result.get('stop_flow'):
                        logger.info(f"[FlowExecutor] Flow stopped by node {node_id}")
                        break

                    if result.get('stop_branch'):
                        logger.info(f"[FlowExecutor] Branch stopped by node {node_id}")
                        continue

                    # Check for delayed execution
                    if result.get('delay_execution'):
                        # Node will schedule its own continuation via Celery
                        from backend.worker.tasks_flow import execute_delayed_node

                        logger.info(f"[FlowExecutor] Node {node_id} requested delay until {result.get('scheduled_for')}")

                        eta = datetime.fromisoformat(result.get('scheduled_for'))

                        # Get next nodes to schedule
                        next_nodes_to_schedule = self._get_next_nodes(node_id)

                        if not next_nodes_to_schedule:
                            logger.info(f"[FlowExecutor] No next nodes after delay node {node_id}. Flow ends.")

                        for next_node in next_nodes_to_schedule:
                            next_node_id = next_node.get('id')
                            logger.info(f"[FlowExecutor] Scheduling next node {next_node_id} for {eta}")
                            execution_id = self._create_delayed_execution(db, next_node_id, eta)

                            def enqueue_delayed_node():
                                task = execute_delayed_node.apply_async(
                                    args=[
                                        self.flow_id,
                                        next_node_id,
                                        self.company_id,
                                        self.variables,
                                        self.trigger_data,
                                    ],
                                    kwargs={"execution_id": execution_id} if execution_id else {},
                                    eta=eta,
                                )
                                if execution_id:
                                    db.query(FlowStepExecution).filter(
                                        FlowStepExecution.id == execution_id
                                    ).update(
                                        {FlowStepExecution.task_id: task.id},
                                        synchronize_session=False,
                                    )
                                return task

                            enqueued, _ = enqueue_company_job_if_active(
                                db,
                                self.company_id,
                                is_still_pending=lambda: (
                                    execution_id is None
                                    or db.query(FlowStepExecution.status)
                                    .filter(FlowStepExecution.id == execution_id)
                                    .scalar()
                                    == "scheduled"
                                ),
                                enqueue=enqueue_delayed_node,
                            )
                            if not enqueued:
                                logger.info(
                                    "[FlowExecutor] Delayed execution cancelled before enqueue execution_id=%s",
                                    execution_id,
                                )

                        # Stop current execution branch
                        continue

                except Exception as e:
                    logger.exception(f"[FlowExecutor] Error executing node {node_id}: {e}")
                    self.execution_log.append({
                        "node_id": node_id,
                        "node_type": node_type,
                        "success": False,
                        "error": str(e)
                    })
                    # Continue with other nodes even if one fails
            else:
                logger.debug(f"[FlowExecutor] No handler for node type: {node_type}, skipping")

            # Add next nodes to queue
            next_nodes = self._get_next_nodes(node_id)
            for next_node in next_nodes:
                if next_node.get('id') not in visited:
                    queue.append(next_node)

    def _create_delayed_execution(
        self,
        db: Session,
        node_id: str,
        scheduled_for: datetime
    ) -> Optional[int]:
        """Persist delayed business-event work. Legacy flows keep Celery-only scheduling."""
        enrollment_id = self.variables.get("flow_enrollment_id") or self.enrollment_id
        if not enrollment_id:
            return None

        enrollment = db.query(FlowEnrollment).filter(
            FlowEnrollment.id == enrollment_id,
            FlowEnrollment.status == "active",
        ).first()
        if not enrollment:
            logger.info("[FlowExecutor] Enrollment inactive; delayed execution will not be persisted")
            return None

        fence_company_job_mutation(db, self.company_id)

        scheduled_for_utc = scheduled_for
        if scheduled_for_utc.tzinfo is None:
            scheduled_for_utc = scheduled_for_utc.replace(tzinfo=timezone.utc)

        dedupe_key = f"{enrollment.id}:{self.flow_id}:{node_id}:{scheduled_for_utc.isoformat()}"
        existing = db.query(FlowStepExecution).filter(
            FlowStepExecution.dedupe_key == dedupe_key
        ).first()
        if existing:
            return existing.id

        execution = FlowStepExecution(
            enrollment_id=enrollment.id,
            flow_id=self.flow_id,
            company_id=self.company_id,
            node_id=node_id,
            scheduled_for=scheduled_for_utc,
            status="scheduled",
            dedupe_key=dedupe_key,
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)
        return execution.id

    def resolve_variables(self, text: str) -> str:
        """
        Resolve variable placeholders in text.

        Supports formats:
        - {{variable_name}}
        - {{trigger.field}}
        - {{nodes.node_id.field}}

        Args:
            text: Text with variable placeholders

        Returns:
            Text with variables resolved
        """
        if not text:
            return text

        if "{{" in text:
            logger.info(f"[FlowExecutor] Resolving vars in: '{text}'")
            # Log keys for debugging (avoid huge dump)
            logger.info(f"[FlowExecutor] Available keys: {[k for k in self.variables.keys() if not k.startswith('trigger.')]}")

        def replace_var(match):
            var_path = match.group(1).strip()
            if var_path == "event.type":
                event_data = self.variables.get("event_data")
                if isinstance(event_data, dict) and event_data.get("type") is not None:
                    return str(event_data.get("type"))
                event_value = self.variables.get("event")
                if isinstance(event_value, dict) and event_value.get("type") is not None:
                    return str(event_value.get("type"))
                if event_value is not None:
                    return str(event_value)

            # Handle nested paths like "trigger.phone" or "nodes.node1.result"
            parts = var_path.split('.')
            value = self.variables

            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    # Variable not found, return original placeholder
                    return match.group(0)

            return str(value) if value is not None else ''

        # Replace {{variable}} patterns
        pattern = r'\{\{([^}]+)\}\}'
        return re.sub(pattern, replace_var, text)
