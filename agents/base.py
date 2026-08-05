from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agents.coordinator import (
    AgentError,
    AgentName,
    AgentResult,
    AgentStatus,
    AgentTask,
    EntityCandidates,
    WarningValue,
)


def success_result(
    task: AgentTask,
    agent_name: AgentName,
    *,
    facts: Mapping[str, Any],
    entities: EntityCandidates | None = None,
    evidence: list[str] | None = None,
    warnings: list[WarningValue] | None = None,
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
        facts=dict(facts),
        entity_candidates=entities or EntityCandidates(),
        evidence_candidates=evidence or [],
        warnings=warnings or [],
    )


def error_result(
    task: AgentTask,
    agent_name: AgentName,
    *,
    status: AgentStatus,
    code: str,
    message: str,
    source: str,
    path: str = "",
    retryable: bool = False,
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
        status=status,
        errors=[
            AgentError(
                code=code,
                path=path,
                message=message,
                source=source,
                retryable=retryable,
                retry_target=agent_name,
            )
        ],
    )
