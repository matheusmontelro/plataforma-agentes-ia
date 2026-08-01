import asyncio
import json
import os

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/agentive_test")

from agents import FunctionTool

from backend.agents_sdk import manager
from backend.agents_sdk.tools.appointment_management_tools import (
    APPOINTMENT_MANAGEMENT_TOOLS,
)
from backend.agents_sdk.tools.confirmation_tools import (
    process_appointment_confirmation,
)
from backend.agents_sdk.tools.referral_tools import REFERRAL_TOOLS


def test_company_bound_tool_hides_and_overrides_llm_company_id():
    captured = {}

    async def invoke(_context, input_json):
        captured.update(json.loads(input_json))
        return "ok"

    raw_tool = FunctionTool(
        name="tenant_sensitive",
        description="test",
        params_json_schema={
            "type": "object",
            "properties": {
                "company_id": {"type": "integer"},
                "phone": {"type": "string"},
            },
            "required": ["company_id", "phone"],
            "additionalProperties": False,
        },
        on_invoke_tool=invoke,
    )

    bound = manager._bind_tool_to_company(raw_tool, 7)
    result = asyncio.run(
        bound.on_invoke_tool(
            None,
            json.dumps({"company_id": 999, "phone": "5500000000007"}),
        )
    )

    assert result == "ok"
    assert "company_id" not in bound.params_json_schema["properties"]
    assert "company_id" not in bound.params_json_schema["required"]
    assert captured == {
        "company_id": 7,
        "phone": "5500000000007",
    }


def test_every_raw_tenant_sensitive_manager_tool_is_bound():
    raw_tools = [
        process_appointment_confirmation,
        *APPOINTMENT_MANAGEMENT_TOOLS,
        *REFERRAL_TOOLS,
    ]

    assert raw_tools
    for raw_tool in raw_tools:
        assert "company_id" in raw_tool.params_json_schema["properties"]
        bound = manager._bind_tool_to_company(raw_tool, 7)
        assert "company_id" not in bound.params_json_schema["properties"]
