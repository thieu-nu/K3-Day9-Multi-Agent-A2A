from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from agents.api_runner import ApiGeneratedAgent
from agents.base import success_result
from agents.coordinator import (
    AgentName,
    AgentStatus,
    AgentTask,
    AtomicJsonOutputStore,
    CoordinatorAgent,
)
from agents.delivery_agent import DeliveryAgent
from agents.order_seller_agent import OrderSellerAgent
from agents.payment_agent import PaymentAgent
from agents.policy_agent import PolicyAgent
from agents.verifier_agent import VerifierAgent
from utils.data_loader import OlistDataLoader
from utils.llm_client import TogetherStructuredClient

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def olist_data() -> OlistDataLoader:
    return OlistDataLoader(ROOT / "data")


def task_for(case_id: str, order_id: str, payload: dict[str, object]) -> AgentTask:
    return AgentTask(
        contract_version="1.0",
        run_id="test-run",
        correlation_id=uuid4().hex,
        task_id=uuid4().hex,
        attempt=1,
        case_id=case_id,
        order_id=order_id,
        policy_version="EC_POLICY_V1",
        requested_at=datetime.now(UTC),
        payload=payload,
    )


def load_case(case_id: str) -> dict[str, object]:
    value = json.loads((ROOT / "input" / f"{case_id}.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{case_id} must contain a JSON object")
    return cast(dict[str, object], value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "expected_issue"),
    [
        ("EC_001", "late_delivery_seller"),
        ("EC_002", "unsupported_late_claim"),
        ("EC_003", "canceled_order_paid"),
        ("EC_004", "valid_split_payment"),
        ("EC_005", "unavailable_order_paid"),
        ("EC_009", "late_delivery_logistics"),
    ],
)
async def test_real_agents_cover_every_policy_branch(
    tmp_path: Path,
    olist_data: OlistDataLoader,
    case_id: str,
    expected_issue: str,
) -> None:
    coordinator = CoordinatorAgent(
        order_seller_agent=OrderSellerAgent(olist_data),
        payment_agent=PaymentAgent(olist_data),
        delivery_agent=DeliveryAgent(olist_data),
        policy_agent=PolicyAgent(),
        verifier_agent=VerifierAgent(olist_data),
        output_store=AtomicJsonOutputStore(tmp_path),
    )

    result = await coordinator.coordinate(
        source_filename=f"{case_id}.json",
        case_input=load_case(case_id),
        run_id="integration-test",
    )

    assert result.success is True
    assert result.final_output is not None
    assert result.final_output.assessment.primary_issue.value == expected_issue
    assert result.handoffs["verifier"] == "PASS"


def test_domain_agents_reconcile_real_order(olist_data: OlistDataLoader) -> None:
    case = load_case("EC_001")
    request = case["customer_request"]
    assert isinstance(request, dict)
    order_id = request["claimed_order_id"]
    assert isinstance(order_id, str)

    order_result = OrderSellerAgent(olist_data).run(
        task_for(
            "EC_001",
            order_id,
            {"lookup_order_id": order_id, "include_product_validation": True},
        )
    )
    payment_result = PaymentAgent(olist_data).run(
        task_for(
            "EC_001",
            order_id,
            {"lookup_order_id": order_id, "reconciliation_tolerance_brl": 0.10},
        )
    )
    delivery_result = DeliveryAgent(olist_data).run(
        task_for("EC_001", order_id, {"lookup_order_id": order_id})
    )

    assert order_result.status == AgentStatus.SUCCESS
    assert payment_result.status == AgentStatus.SUCCESS
    assert delivery_result.status == AgentStatus.SUCCESS
    assert order_result.facts["item_total_brl"] == payment_result.facts["item_total_brl_check"]
    assert (
        order_result.facts["freight_total_brl"] == payment_result.facts["freight_total_brl_check"]
    )
    assert payment_result.facts["is_reconciled"] is True
    assert delivery_result.facts["attribution_candidate"] == "seller"


def test_domain_agent_rejects_mismatched_lookup(olist_data: OlistDataLoader) -> None:
    result = PaymentAgent(olist_data).run(
        task_for(
            "EC_001",
            "e2a03ccf5ea816036608b2d8c3ab8e60",
            {
                "lookup_order_id": "8067c5e4834f3c0a3c8a4e921d65c5b1",
                "reconciliation_tolerance_brl": 0.10,
            },
        )
    )

    assert result.status == AgentStatus.INVALID_INPUT
    assert result.errors[0].code == "INVALID_AGENT_PAYLOAD"


class FakeGeneratingClient:
    async def complete_structured(self, **kwargs: Any) -> Any:
        request = json.loads(kwargs["user_prompt"])
        tool_result = request["source"]["tool_result"]
        facts = dict(tool_result["facts"])
        facts["payment_count"] = 2
        facts["is_split_payment"] = True
        response = {
            "agent_name": request["agent_name"],
            "task_id": request["task_id"],
            "source_digest": request["source_digest"],
            "facts": facts,
            "entity_candidates": tool_result["entity_candidates"],
            "evidence_candidates": tool_result["evidence_candidates"],
            "warnings": [],
        }
        return kwargs["response_model"].model_validate_json(json.dumps(response))


@pytest.mark.asyncio
async def test_api_generated_response_replaces_tool_result(olist_data: OlistDataLoader) -> None:
    case = load_case("EC_001")
    request = case["customer_request"]
    assert isinstance(request, dict)
    order_id = request["claimed_order_id"]
    assert isinstance(order_id, str)
    agent = ApiGeneratedAgent(
        agent_name=AgentName.PAYMENT,
        tool_runner=PaymentAgent(olist_data),
        client=cast(TogetherStructuredClient, FakeGeneratingClient()),
    )

    result = await agent.run(
        task_for(
            "EC_001",
            order_id,
            {"lookup_order_id": order_id, "reconciliation_tolerance_brl": 0.10},
        )
    )

    assert result.facts["payment_count"] == 2
    assert result.facts["is_split_payment"] is True
    api_warning = result.warnings[-1]
    assert isinstance(api_warning, dict)
    assert api_warning["type"] == "api_generation"


class RecordingPolicyRunner:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def run(self, task: AgentTask) -> Any:
        self.events.append("python_policy")
        return success_result(
            task,
            AgentName.POLICY,
            facts={
                "bundle_version": 1,
                "bundle_digest": "0" * 64,
                "matched_rule_priority": 6,
                "primary_issue": "unsupported_late_claim",
                "case_status": "no_action",
                "confidence": 1.0,
                "confidence_basis": ["rule_match_exact"],
                "selected_entities": {
                    "order_ids": [task.order_id],
                    "item_ids": [],
                    "seller_ids": [],
                    "payment_ids": [],
                },
                "ranked_causes": [{"cause_code": "DELIVERY_WITHIN_ESTIMATE", "rank": 1}],
                "responsible_parties": [],
                "recommended_refund_brl": 0.0,
                "resolution_actions": ["reject_late_refund"],
                "selected_evidence_ids": ["policy:DELIVERY_WITHIN_ESTIMATE"],
                "excluded_higher_priority_rules": [
                    {"priority": priority, "reason_code": "RULE_CONDITION_NOT_MET"}
                    for priority in range(1, 6)
                ],
            },
        )


class RecordingPolicyClient:
    def __init__(self, events: list[str], *, change_locked_rule: bool = False) -> None:
        self.events = events
        self.change_locked_rule = change_locked_rule

    async def complete_structured(self, **kwargs: Any) -> Any:
        self.events.append("policy_api")
        request = json.loads(kwargs["user_prompt"])
        tool_result = request["source"]["tool_result"]
        facts = dict(tool_result["facts"])
        facts["confidence"] = 0.73
        facts["confidence_basis"] = ["api_reviewed_python_policy"]
        if self.change_locked_rule:
            facts["resolution_actions"] = ["explain_valid_split_payment"]
        response = {
            "agent_name": request["agent_name"],
            "task_id": request["task_id"],
            "source_digest": request["source_digest"],
            "facts": facts,
            "entity_candidates": tool_result["entity_candidates"],
            "evidence_candidates": tool_result["evidence_candidates"],
            "warnings": [],
        }
        return kwargs["response_model"].model_validate_json(json.dumps(response))


@pytest.mark.asyncio
async def test_policy_python_evaluation_runs_before_api_and_locks_rule() -> None:
    events: list[str] = []
    task = task_for(
        "EC_002",
        "e2a03ccf5ea816036608b2d8c3ab8e60",
        {"policy_version": "EC_POLICY_V1"},
    )
    agent = ApiGeneratedAgent(
        agent_name=AgentName.POLICY,
        tool_runner=RecordingPolicyRunner(events),
        client=cast(TogetherStructuredClient, RecordingPolicyClient(events)),
    )

    result = await agent.run(task)

    assert events == ["python_policy", "policy_api"]
    assert result.status == AgentStatus.SUCCESS
    assert result.facts["resolution_actions"] == ["reject_late_refund"]
    assert result.facts["confidence"] == 0.73
    assert any(
        isinstance(warning, dict) and warning.get("type") == "python_policy_evaluation"
        for warning in result.warnings
    )


@pytest.mark.asyncio
async def test_policy_api_cannot_override_python_rule() -> None:
    events: list[str] = []
    task = task_for(
        "EC_002",
        "e2a03ccf5ea816036608b2d8c3ab8e60",
        {"policy_version": "EC_POLICY_V1"},
    )
    agent = ApiGeneratedAgent(
        agent_name=AgentName.POLICY,
        tool_runner=RecordingPolicyRunner(events),
        client=cast(
            TogetherStructuredClient,
            RecordingPolicyClient(events, change_locked_rule=True),
        ),
    )

    result = await agent.run(task)

    assert events == ["python_policy", "policy_api"]
    assert result.status == AgentStatus.CONFLICT
    assert result.errors[0].code == "POLICY_API_MISMATCH"
    assert "resolution_actions" in result.errors[0].path
