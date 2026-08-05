from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from agents.coordinator import (
    AgentError,
    AgentName,
    AgentResult,
    AgentStatus,
    AgentTask,
    AtomicJsonOutputStore,
    CoordinatorAgent,
    CoordinatorConfig,
    CoordinatorPhase,
    EntityCandidates,
)
from utils.llm_client import LlmConfigurationError, TogetherStructuredClient

AgentFactory = Callable[[AgentTask, int], AgentResult | Awaitable[AgentResult]]


class FunctionAgent:
    def __init__(self, factory: AgentFactory) -> None:
        self.factory = factory
        self.calls: list[AgentTask] = []

    async def run(self, task: AgentTask) -> AgentResult:
        self.calls.append(task)
        result = self.factory(task, len(self.calls))
        if isinstance(result, Awaitable):
            return await result
        return result


class MemoryTraceSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))


class ParallelGate:
    def __init__(self, expected: int) -> None:
        self.expected = expected
        self.started: set[AgentName] = set()
        self.ready = asyncio.Event()

    async def wait(self, agent_name: AgentName) -> None:
        self.started.add(agent_name)
        if len(self.started) == self.expected:
            self.ready.set()
        await asyncio.wait_for(self.ready.wait(), timeout=1)


@pytest.fixture
def case_input() -> dict[str, Any]:
    return {
        "case_id": "EC_001",
        "opened_at": "2018-10-18T00:00:00-03:00",
        "customer_request": {
            "language": "vi",
            "message": "Tôi cho rằng đơn hàng được giao trễ.",
            "claimed_order_id": "e2a03ccf5ea816036608b2d8c3ab8e60",
        },
        "policy_version": "EC_POLICY_V1",
    }


def successful_result(
    task: AgentTask,
    agent_name: AgentName,
    *,
    facts: dict[str, Any] | None = None,
    entities: EntityCandidates | None = None,
    evidence: list[str] | None = None,
) -> AgentResult:
    return AgentResult(
        contract_version=task.contract_version,
        run_id=task.run_id,
        correlation_id=task.correlation_id,
        task_id=task.task_id,
        attempt=task.attempt,
        case_id=task.case_id,
        order_id=task.order_id,
        policy_version=task.policy_version,
        agent_name=agent_name,
        status=AgentStatus.SUCCESS,
        facts=facts or {},
        entity_candidates=entities or EntityCandidates(),
        evidence_candidates=evidence or [],
    )


def failed_result(
    task: AgentTask,
    agent_name: AgentName,
    *,
    code: str = "AGENT_INTERNAL_ERROR",
) -> AgentResult:
    return AgentResult(
        contract_version=task.contract_version,
        run_id=task.run_id,
        correlation_id=task.correlation_id,
        task_id=task.task_id,
        attempt=task.attempt,
        case_id=task.case_id,
        order_id=task.order_id,
        policy_version=task.policy_version,
        agent_name=agent_name,
        status=AgentStatus.INTERNAL_ERROR,
        errors=[
            AgentError(
                code=code,
                message="temporary failure",
                source=agent_name.value,
                retryable=True,
                retry_target=agent_name,
            )
        ],
    )


def order_facts() -> dict[str, Any]:
    return {
        "order_found": True,
        "order": {
            "order_id": "e2a03ccf5ea816036608b2d8c3ab8e60",
            "order_status": "delivered",
        },
        "items": [
            {
                "order_item_id": 1,
                "seller_id": "seller-1",
                "price_brl": 100.0,
                "freight_value_brl": 15.0,
            }
        ],
        "item_total_brl": 100.0,
        "freight_total_brl": 15.0,
        "violating_seller_ids": ["seller-1"],
    }


def payment_facts(*, item_check: float = 100.0) -> dict[str, Any]:
    return {
        "payments": [{"payment_sequential": 1, "payment_value_brl": 115.0}],
        "payment_count": 1,
        "payment_total_brl": 115.0,
        "item_total_brl_check": item_check,
        "freight_total_brl_check": 15.0,
        "expected_total_brl": 115.0,
        "difference_brl": 0.0,
        "is_reconciled": True,
        "is_split_payment": False,
    }


def build_domain_agents(
    gate: ParallelGate | None = None,
) -> tuple[FunctionAgent, FunctionAgent, FunctionAgent]:
    async def order(task: AgentTask, _: int) -> AgentResult:
        if gate:
            await gate.wait(AgentName.ORDER_SELLER)
        return successful_result(
            task,
            AgentName.ORDER_SELLER,
            facts=order_facts(),
            entities=EntityCandidates(
                order_ids=[task.order_id],
                item_ids=[f"{task.order_id}:1"],
                seller_ids=["seller-1"],
            ),
            evidence=[
                f"order:{task.order_id}",
                f"item:{task.order_id}:1",
                "seller:seller-1",
            ],
        )

    async def payment(task: AgentTask, _: int) -> AgentResult:
        if gate:
            await gate.wait(AgentName.PAYMENT)
        return successful_result(
            task,
            AgentName.PAYMENT,
            facts=payment_facts(),
            entities=EntityCandidates(payment_ids=[f"{task.order_id}:1"]),
            evidence=[f"payment:{task.order_id}:1"],
        )

    async def delivery(task: AgentTask, _: int) -> AgentResult:
        if gate:
            await gate.wait(AgentName.DELIVERY)
        return successful_result(
            task,
            AgentName.DELIVERY,
            facts={
                "delivered_after_estimate": True,
                "delivery_within_estimate": False,
                "attribution_candidate": "seller",
                "responsible_seller_candidates": ["seller-1"],
            },
        )

    return FunctionAgent(order), FunctionAgent(payment), FunctionAgent(delivery)


def build_policy_agent() -> FunctionAgent:
    def policy(task: AgentTask, _: int) -> AgentResult:
        bundle = task.payload["evidence_bundle"]
        return successful_result(
            task,
            AgentName.POLICY,
            facts={
                "bundle_version": bundle["bundle_version"],
                "bundle_digest": bundle["bundle_digest"],
                "matched_rule_priority": 3,
                "primary_issue": "late_delivery_seller",
                "case_status": "action_required",
                "confidence": 1.0,
                "confidence_basis": ["critical_facts_complete", "rule_match_exact"],
                "selected_entities": bundle["entity_candidates"],
                "ranked_causes": [{"cause_code": "SELLER_HANDOFF_AFTER_LIMIT", "rank": 1}],
                "responsible_parties": [{"party_type": "seller", "party_id": "seller-1"}],
                "recommended_refund_brl": 15.0,
                "resolution_actions": ["refund_freight"],
                "selected_evidence_ids": [
                    f"order:{task.order_id}",
                    f"item:{task.order_id}:1",
                    f"payment:{task.order_id}:1",
                    "seller:seller-1",
                    "policy:SELLER_HANDOFF_AFTER_LIMIT",
                ],
                "excluded_higher_priority_rules": [],
            },
        )

    return FunctionAgent(policy)


def build_verifier_agent(
    *, fail_first_for: AgentName | None = None, stale_digest: bool = False
) -> FunctionAgent:
    def verifier(task: AgentTask, call_number: int) -> AgentResult:
        if fail_first_for and call_number == 1:
            facts = {
                "verdict": "FAIL",
                "draft_version": task.payload["draft_version"],
                "draft_digest": task.payload["draft_digest"],
                "checks": {"policy": False},
                "errors": [
                    AgentError(
                        code="INVALID_EVIDENCE",
                        message="policy must select evidence again",
                        source="verifier",
                        retryable=True,
                        retry_target=fail_first_for,
                    ).model_dump(mode="json")
                ],
                "warnings": [],
            }
        else:
            digest = "0" * 64 if stale_digest else task.payload["draft_digest"]
            facts = {
                "verdict": "PASS",
                "draft_version": task.payload["draft_version"],
                "draft_digest": digest,
                "checks": {
                    "schema": True,
                    "identity": True,
                    "entities": True,
                    "evidence": True,
                    "financials": True,
                    "policy": True,
                    "limits": True,
                },
                "errors": [],
                "warnings": [],
            }
        return successful_result(task, AgentName.VERIFIER, facts=facts)

    return FunctionAgent(verifier)


def build_coordinator(
    tmp_path: Path,
    *,
    order: FunctionAgent | None = None,
    payment: FunctionAgent | None = None,
    delivery: FunctionAgent | None = None,
    policy: FunctionAgent | None = None,
    verifier: FunctionAgent | None = None,
    trace: MemoryTraceSink | None = None,
) -> CoordinatorAgent:
    default_order, default_payment, default_delivery = build_domain_agents()
    return CoordinatorAgent(
        order_seller_agent=order or default_order,
        payment_agent=payment or default_payment,
        delivery_agent=delivery or default_delivery,
        policy_agent=policy or build_policy_agent(),
        verifier_agent=verifier or build_verifier_agent(),
        output_store=AtomicJsonOutputStore(tmp_path / "output"),
        trace_sink=trace,
        config=CoordinatorConfig(agent_timeout_seconds=2),
        clock=lambda: datetime(2026, 8, 5, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_happy_path_fans_out_and_writes_only_after_pass(
    tmp_path: Path, case_input: dict[str, Any]
) -> None:
    gate = ParallelGate(expected=3)
    order, payment, delivery = build_domain_agents(gate)
    trace = MemoryTraceSink()
    coordinator = build_coordinator(
        tmp_path,
        order=order,
        payment=payment,
        delivery=delivery,
        trace=trace,
    )

    result = await coordinator.coordinate(
        source_filename="EC_001.json", case_input=case_input, run_id="run-1"
    )

    assert result.success is True
    assert result.phase == CoordinatorPhase.WRITTEN
    assert gate.started == {
        AgentName.ORDER_SELLER,
        AgentName.PAYMENT,
        AgentName.DELIVERY,
    }
    output_path = Path(result.output_path or "")
    assert output_path.exists()
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["case_id"] == "EC_001"
    assert output["assessment"]["primary_issue"] == "late_delivery_seller"
    assert output["financial_resolution"]["recommended_refund_brl"] == 15.0
    event_types = [event["event_type"] for event in trace.events]
    assert event_types.index("verification_completed") < event_types.index("output_written")


@pytest.mark.asyncio
async def test_invalid_filename_never_calls_agents(
    tmp_path: Path, case_input: dict[str, Any]
) -> None:
    order, payment, delivery = build_domain_agents()
    policy = build_policy_agent()
    verifier = build_verifier_agent()
    coordinator = build_coordinator(
        tmp_path,
        order=order,
        payment=payment,
        delivery=delivery,
        policy=policy,
        verifier=verifier,
    )

    result = await coordinator.coordinate(
        source_filename="EC_999.json", case_input=case_input, run_id="run-1"
    )

    assert result.success is False
    assert result.errors[0].code == "CASE_FILENAME_MISMATCH"
    assert not order.calls and not payment.calls and not delivery.calls
    assert not policy.calls and not verifier.calls
    assert not (tmp_path / "output").exists()


@pytest.mark.asyncio
async def test_retryable_agent_failure_is_retried_once(
    tmp_path: Path, case_input: dict[str, Any]
) -> None:
    good_order, payment, delivery = build_domain_agents()

    async def transient_order(task: AgentTask, call_number: int) -> AgentResult:
        if call_number == 1:
            return failed_result(task, AgentName.ORDER_SELLER)
        return await cast(Awaitable[AgentResult], good_order.factory(task, call_number))

    order = FunctionAgent(transient_order)
    coordinator = build_coordinator(tmp_path, order=order, payment=payment, delivery=delivery)

    result = await coordinator.coordinate(
        source_filename="EC_001.json", case_input=case_input, run_id="run-1"
    )

    assert result.success is True
    assert len(order.calls) == 2


@pytest.mark.asyncio
async def test_domain_total_conflict_reruns_order_and_payment(
    tmp_path: Path, case_input: dict[str, Any]
) -> None:
    order, good_payment, delivery = build_domain_agents()

    async def conflicting_payment(task: AgentTask, call_number: int) -> AgentResult:
        if call_number > 1:
            return await cast(Awaitable[AgentResult], good_payment.factory(task, call_number))
        return successful_result(
            task,
            AgentName.PAYMENT,
            facts=payment_facts(item_check=99.0),
            entities=EntityCandidates(payment_ids=[f"{task.order_id}:1"]),
            evidence=[f"payment:{task.order_id}:1"],
        )

    payment = FunctionAgent(conflicting_payment)
    coordinator = build_coordinator(tmp_path, order=order, payment=payment, delivery=delivery)

    result = await coordinator.coordinate(
        source_filename="EC_001.json", case_input=case_input, run_id="run-1"
    )

    assert result.success is True
    assert len(order.calls) == 2
    assert len(payment.calls) == 2
    assert len(delivery.calls) == 1


@pytest.mark.asyncio
async def test_verifier_failure_retries_policy_with_new_draft(
    tmp_path: Path, case_input: dict[str, Any]
) -> None:
    policy = build_policy_agent()
    verifier = build_verifier_agent(fail_first_for=AgentName.POLICY)
    coordinator = build_coordinator(tmp_path, policy=policy, verifier=verifier)

    result = await coordinator.coordinate(
        source_filename="EC_001.json", case_input=case_input, run_id="run-1"
    )

    assert result.success is True
    assert len(policy.calls) == 2
    assert len(verifier.calls) == 2
    assert verifier.calls[0].payload["draft_version"] == 1
    assert verifier.calls[1].payload["draft_version"] == 2


@pytest.mark.asyncio
async def test_stale_verifier_pass_never_writes_output(
    tmp_path: Path, case_input: dict[str, Any]
) -> None:
    coordinator = build_coordinator(tmp_path, verifier=build_verifier_agent(stale_digest=True))

    result = await coordinator.coordinate(
        source_filename="EC_001.json", case_input=case_input, run_id="run-1"
    )

    assert result.success is False
    assert result.errors[0].code == "STALE_VERIFICATION_RESULT"
    assert not (tmp_path / "output" / "EC_001.json").exists()


def test_together_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    with pytest.raises(LlmConfigurationError):
        TogetherStructuredClient()
