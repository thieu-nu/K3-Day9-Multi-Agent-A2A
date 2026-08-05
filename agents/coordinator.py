from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import time
from collections.abc import Awaitable, Callable, Hashable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, TypedDict, TypeVar
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

CONTRACT_VERSION = "1.0"
POLICY_VERSION = "EC_POLICY_V1"
CASE_ID_PATTERN = re.compile(r"^EC_[0-9]{3}$")
ORDER_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
MONEY_QUANTUM = Decimal("0.01")


class CoordinatorPhase(StrEnum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    DISPATCHED = "DISPATCHED"
    COLLECTED = "COLLECTED"
    POLICY_DECIDED = "POLICY_DECIDED"
    DRAFTED = "DRAFTED"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    WRITTEN = "WRITTEN"
    FAILED = "FAILED"


class AgentName(StrEnum):
    ORDER_SELLER = "order_seller"
    PAYMENT = "payment"
    DELIVERY = "delivery"
    POLICY = "policy"
    VERIFIER = "verifier"
    COORDINATOR = "coordinator"


class AgentStatus(StrEnum):
    SUCCESS = "success"
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    DATA_ERROR = "data_error"
    CONFLICT = "conflict"
    INTERNAL_ERROR = "internal_error"


class PrimaryIssue(StrEnum):
    CANCELED_ORDER_PAID = "canceled_order_paid"
    UNAVAILABLE_ORDER_PAID = "unavailable_order_paid"
    LATE_DELIVERY_SELLER = "late_delivery_seller"
    LATE_DELIVERY_LOGISTICS = "late_delivery_logistics"
    VALID_SPLIT_PAYMENT = "valid_split_payment"
    UNSUPPORTED_LATE_CLAIM = "unsupported_late_claim"


class RootCauseCode(StrEnum):
    SELLER_HANDOFF_AFTER_LIMIT = "SELLER_HANDOFF_AFTER_LIMIT"
    CARRIER_DELIVERED_AFTER_ESTIMATE = "CARRIER_DELIVERED_AFTER_ESTIMATE"
    ORDER_CANCELED_AFTER_PAYMENT = "ORDER_CANCELED_AFTER_PAYMENT"
    ORDER_UNAVAILABLE_AFTER_PAYMENT = "ORDER_UNAVAILABLE_AFTER_PAYMENT"
    MULTIPLE_PAYMENTS_RECONCILED = "MULTIPLE_PAYMENTS_RECONCILED"
    DELIVERY_WITHIN_ESTIMATE = "DELIVERY_WITHIN_ESTIMATE"


class ResolutionAction(StrEnum):
    ISSUE_FULL_REFUND = "issue_full_refund"
    REFUND_FREIGHT = "refund_freight"
    EXPLAIN_VALID_SPLIT_PAYMENT = "explain_valid_split_payment"
    REJECT_LATE_REFUND = "reject_late_refund"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CustomerRequest(StrictModel):
    language: Literal["vi"]
    message: str = Field(min_length=1)
    claimed_order_id: str = Field(pattern=ORDER_ID_PATTERN.pattern)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message must not be blank")
        return stripped


class CaseInput(StrictModel):
    case_id: str = Field(pattern=CASE_ID_PATTERN.pattern)
    opened_at: datetime
    customer_request: CustomerRequest
    policy_version: Literal["EC_POLICY_V1"]


class AgentError(StrictModel):
    code: str = Field(min_length=1)
    path: str = ""
    message: str = Field(min_length=1)
    source: str = ""
    retryable: bool = False
    retry_target: AgentName = AgentName.COORDINATOR


class EntityCandidates(StrictModel):
    order_ids: list[str] = Field(default_factory=list)
    item_ids: list[str] = Field(default_factory=list)
    seller_ids: list[str] = Field(default_factory=list)
    payment_ids: list[str] = Field(default_factory=list)

    @field_validator("order_ids", "item_ids", "seller_ids", "payment_ids")
    @classmethod
    def require_unique_non_blank(cls, values: list[str]) -> list[str]:
        if any(not value for value in values):
            raise ValueError("entity IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("entity IDs must be unique")
        return values


class AgentTask(StrictModel):
    contract_version: Literal["1.0"]
    run_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    attempt: int = Field(ge=1)
    case_id: str = Field(pattern=CASE_ID_PATTERN.pattern)
    order_id: str = Field(pattern=ORDER_ID_PATTERN.pattern)
    policy_version: Literal["EC_POLICY_V1"]
    requested_at: datetime
    payload: dict[str, Any]


WarningValue = str | dict[str, Any]


class AgentResult(StrictModel):
    contract_version: Literal["1.0"]
    run_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    attempt: int = Field(ge=1)
    case_id: str = Field(pattern=CASE_ID_PATTERN.pattern)
    order_id: str = Field(pattern=ORDER_ID_PATTERN.pattern)
    policy_version: Literal["EC_POLICY_V1"]
    agent_name: AgentName
    status: AgentStatus
    facts: dict[str, Any] = Field(default_factory=dict)
    entity_candidates: EntityCandidates = Field(default_factory=EntityCandidates)
    evidence_candidates: list[str] = Field(default_factory=list)
    warnings: list[WarningValue] = Field(default_factory=list)
    errors: list[AgentError] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status_errors(self) -> AgentResult:
        if self.status == AgentStatus.SUCCESS and self.errors:
            raise ValueError("successful AgentResult must not contain errors")
        if self.status != AgentStatus.SUCCESS and not self.errors:
            raise ValueError("non-success AgentResult must contain errors")
        if len(self.evidence_candidates) != len(set(self.evidence_candidates)):
            raise ValueError("evidence candidates must be unique")
        return self


class EvidenceBundle(StrictModel):
    contract_version: Literal["1.0"]
    run_id: str
    correlation_id: str
    case_id: str = Field(pattern=CASE_ID_PATTERN.pattern)
    order_id: str = Field(pattern=ORDER_ID_PATTERN.pattern)
    policy_version: Literal["EC_POLICY_V1"]
    bundle_version: int = Field(ge=1)
    bundle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_status: dict[str, Literal["success"]]
    order_facts: dict[str, Any]
    item_seller_facts: dict[str, Any]
    payment_facts: dict[str, Any]
    delivery_facts: dict[str, Any]
    entity_candidates: EntityCandidates
    evidence_candidates: list[str]
    warnings: list[WarningValue]


class RankedCause(StrictModel):
    cause_code: RootCauseCode
    rank: int = Field(ge=1, le=3)


class ResponsibleParty(StrictModel):
    party_type: Literal["seller", "platform", "logistics_provider"]
    party_id: str = Field(min_length=1)


class PolicyDecision(StrictModel):
    bundle_version: int = Field(ge=1)
    bundle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched_rule_priority: int = Field(ge=1, le=6)
    primary_issue: PrimaryIssue
    case_status: Literal["action_required", "no_action"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    confidence_basis: list[str] = Field(min_length=1)
    selected_entities: EntityCandidates
    ranked_causes: list[RankedCause] = Field(min_length=1, max_length=3)
    responsible_parties: list[ResponsibleParty] = Field(max_length=3)
    recommended_refund_brl: Decimal = Field(ge=0)
    resolution_actions: list[ResolutionAction] = Field(min_length=1, max_length=5)
    selected_evidence_ids: list[str] = Field(min_length=1, max_length=10)
    excluded_higher_priority_rules: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_uniqueness(self) -> PolicyDecision:
        ranks = [cause.rank for cause in self.ranked_causes]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("cause ranks must start at 1 and be contiguous")
        if len(self.selected_evidence_ids) != len(set(self.selected_evidence_ids)):
            raise ValueError("selected evidence IDs must be unique")
        if len(self.resolution_actions) != len(set(self.resolution_actions)):
            raise ValueError("resolution actions must be unique")
        self._validate_status_resolution(
            self.case_status,
            self.recommended_refund_brl,
            self.resolution_actions,
        )
        return self

    @staticmethod
    def _validate_status_resolution(
        case_status: Literal["action_required", "no_action"],
        refund: Decimal,
        actions: list[ResolutionAction],
    ) -> None:
        refund_actions = {
            ResolutionAction.ISSUE_FULL_REFUND,
            ResolutionAction.REFUND_FREIGHT,
        }
        no_action_actions = {
            ResolutionAction.EXPLAIN_VALID_SPLIT_PAYMENT,
            ResolutionAction.REJECT_LATE_REFUND,
        }
        selected = set(actions)
        if case_status == "action_required" and (
            refund <= 0 or not selected or not selected.issubset(refund_actions)
        ):
            raise ValueError("action_required requires a positive refund and refund actions only")
        if case_status == "no_action" and (
            refund != 0 or not selected or not selected.issubset(no_action_actions)
        ):
            raise ValueError(
                "no_action requires zero refund and explanation/rejection actions only"
            )


class Assessment(StrictModel):
    primary_issue: PrimaryIssue
    case_status: Literal["action_required", "no_action"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class AffectedEntities(StrictModel):
    order_ids: list[str] = Field(max_length=5)
    item_ids: list[str] = Field(max_length=5)
    seller_ids: list[str] = Field(max_length=5)
    payment_ids: list[str] = Field(max_length=5)

    @field_validator("order_ids", "item_ids", "seller_ids", "payment_ids")
    @classmethod
    def ensure_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("affected entity IDs must be unique")
        return values


class RootCauseAnalysis(StrictModel):
    ranked_causes: list[RankedCause] = Field(min_length=1, max_length=3)
    responsible_parties: list[ResponsibleParty] = Field(max_length=3)


class FinancialResolution(StrictModel):
    currency: Literal["BRL"]
    item_total_brl: float = Field(ge=0, allow_inf_nan=False)
    freight_total_brl: float = Field(ge=0, allow_inf_nan=False)
    payment_total_brl: float = Field(ge=0, allow_inf_nan=False)
    recommended_refund_brl: float = Field(ge=0, allow_inf_nan=False)


class FinalOutput(StrictModel):
    case_id: str = Field(pattern=CASE_ID_PATTERN.pattern)
    assessment: Assessment
    affected_entities: AffectedEntities
    root_cause_analysis: RootCauseAnalysis
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    financial_resolution: FinancialResolution
    resolution_actions: list[ResolutionAction] = Field(min_length=1, max_length=5)

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("evidence IDs must be unique")
        return values

    @model_validator(mode="after")
    def validate_status_resolution(self) -> FinalOutput:
        PolicyDecision._validate_status_resolution(
            self.assessment.case_status,
            Decimal(str(self.financial_resolution.recommended_refund_brl)),
            self.resolution_actions,
        )
        return self


class VerificationResult(StrictModel):
    verdict: Literal["PASS", "FAIL"]
    draft_version: int = Field(ge=1)
    draft_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: dict[str, bool]
    recomputed_values: dict[str, Decimal] = Field(default_factory=dict)
    errors: list[AgentError] = Field(default_factory=list)
    warnings: list[WarningValue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_verdict(self) -> VerificationResult:
        required_checks = {
            "schema",
            "identity",
            "entities",
            "evidence",
            "financials",
            "policy",
            "limits",
        }
        if self.verdict == "PASS":
            if self.errors:
                raise ValueError("PASS verification must not contain errors")
            if not required_checks.issubset(self.checks):
                raise ValueError("PASS verification is missing required checks")
            if not all(self.checks[name] for name in required_checks):
                raise ValueError("all required checks must pass")
        elif not self.errors:
            raise ValueError("FAIL verification must contain errors")
        return self


class CoordinatorResult(StrictModel):
    success: bool
    phase: CoordinatorPhase
    run_id: str
    correlation_id: str
    case_id: str | None = None
    handoffs: dict[str, str] = Field(default_factory=dict)
    final_output: FinalOutput | None = None
    output_path: str | None = None
    errors: list[AgentError] = Field(default_factory=list)


AgentRunValue = AgentResult | Mapping[str, Any]


class AgentRunner(Protocol):
    def run(self, task: AgentTask) -> AgentRunValue | Awaitable[AgentRunValue]: ...


class TraceSink(Protocol):
    def emit(self, event: Mapping[str, Any]) -> None | Awaitable[None]: ...


class OutputStore(Protocol):
    def write(self, filename: str, value: Mapping[str, Any]) -> Path | Awaitable[Path]: ...


class JsonlTraceSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def emit(self, event: Mapping[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        async with self._lock:
            await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)


class AtomicJsonOutputStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    async def write(self, filename: str, value: Mapping[str, Any]) -> Path:
        if not re.fullmatch(r"EC_[0-9]{3}\.json", filename):
            raise ValueError("output filename must match EC_NNN.json")
        return await asyncio.to_thread(self._write_sync, filename, value)

    def _write_sync(self, filename: str, value: Mapping[str, Any]) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / filename
        temporary = self.directory / f".{filename}.{uuid4().hex}.tmp"
        payload = (
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
                allow_nan=False,
            )
            + "\n"
        )
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination


class CoordinationFailure(RuntimeError):
    def __init__(self, errors: Sequence[AgentError]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(f"{error.code}: {error.message}" for error in errors))


class CoordinatorConfig(StrictModel):
    agent_timeout_seconds: float = Field(default=60.0, gt=0)
    max_agent_attempts: int = Field(default=2, ge=1, le=5)
    max_domain_conflict_retries: int = Field(default=1, ge=0, le=3)
    max_verification_rounds: int = Field(default=2, ge=1, le=5)
    graph_recursion_limit: int = Field(default=30, ge=10, le=100)
    payment_tolerance_brl: Decimal = Field(default=Decimal("0.10"), ge=0)


def _merge_domain_results(
    left: dict[str, AgentResult], right: dict[str, AgentResult]
) -> dict[str, AgentResult]:
    return {**left, **right}


class CoordinatorGraphState(TypedDict, total=False):
    raw_case: dict[str, Any]
    source_filename: str
    run_id: str
    correlation_id: str
    phase: CoordinatorPhase
    case: CaseInput
    domain_results: Annotated[dict[str, AgentResult], _merge_domain_results]
    domain_conflict_count: int
    bundle: EvidenceBundle
    policy_result: AgentResult
    policy_decision: PolicyDecision
    draft: FinalOutput
    draft_version: int
    draft_digest: str
    verification: VerificationResult
    verification_round: int
    retry_targets: list[AgentName]
    handoffs: dict[str, str]
    errors: list[AgentError]
    output_path: str


Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
T = TypeVar("T")


class CoordinatorAgent:
    def __init__(
        self,
        *,
        order_seller_agent: AgentRunner,
        payment_agent: AgentRunner,
        delivery_agent: AgentRunner,
        policy_agent: AgentRunner,
        verifier_agent: AgentRunner,
        output_store: OutputStore | None = None,
        trace_sink: TraceSink | None = None,
        config: CoordinatorConfig | None = None,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        self._agents: dict[AgentName, AgentRunner] = {
            AgentName.ORDER_SELLER: order_seller_agent,
            AgentName.PAYMENT: payment_agent,
            AgentName.DELIVERY: delivery_agent,
            AgentName.POLICY: policy_agent,
            AgentName.VERIFIER: verifier_agent,
        }
        self._output_store = output_store or AtomicJsonOutputStore("output")
        self._trace_sink = trace_sink
        self._config = config or CoordinatorConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._seen_cases: set[tuple[str, str]] = set()
        self._seen_lock = asyncio.Lock()
        self.graph = self._build_graph()

    async def coordinate(
        self,
        *,
        source_filename: str,
        case_input: Mapping[str, Any],
        run_id: str | None = None,
    ) -> CoordinatorResult:
        resolved_run_id = (run_id or self._id_factory()).strip()
        correlation_id = self._id_factory()
        initial: CoordinatorGraphState = {
            "raw_case": dict(case_input),
            "source_filename": source_filename,
            "run_id": resolved_run_id,
            "correlation_id": correlation_id,
            "phase": CoordinatorPhase.RECEIVED,
            "domain_results": {},
            "domain_conflict_count": 0,
            "verification_round": 0,
            "handoffs": {},
            "errors": [],
        }
        await self._emit(initial, "case_received", "success", handoff_to="validate")

        try:
            final_state = await self.graph.ainvoke(
                initial,
                config={"recursion_limit": self._config.graph_recursion_limit},
            )
        except CoordinationFailure as failure:
            failed_state: CoordinatorGraphState = {
                **initial,
                "phase": CoordinatorPhase.FAILED,
                "errors": failure.errors,
            }
            await self._emit(
                failed_state,
                "case_failed",
                "failed",
                output_summary={"error_codes": [error.code for error in failure.errors]},
            )
            return self._result_from_state(failed_state)
        except Exception as exc:
            error = AgentError(
                code="COORDINATOR_INTERNAL_ERROR",
                message=f"{type(exc).__name__}: {exc}",
                source="coordinator",
                retryable=False,
                retry_target=AgentName.COORDINATOR,
            )
            failed_state = {**initial, "phase": CoordinatorPhase.FAILED, "errors": [error]}
            await self._emit(
                failed_state,
                "case_failed",
                "failed",
                output_summary={"error_codes": [error.code]},
            )
            return self._result_from_state(failed_state)

        return self._result_from_state(final_state)

    def _build_graph(self) -> Any:
        builder = StateGraph(CoordinatorGraphState)
        builder.add_node("validate", self._validate_node)
        builder.add_node("order_seller", self._order_seller_node)
        builder.add_node("payment", self._payment_node)
        builder.add_node("delivery", self._delivery_node)
        builder.add_node("collect", self._collect_node)
        builder.add_node("retry_domains", self._retry_domains_node)
        builder.add_node("policy", self._policy_node)
        builder.add_node("draft", self._draft_node)
        builder.add_node("verify", self._verify_node)
        builder.add_node("write", self._write_node)
        builder.add_node("fail", self._fail_node)

        builder.add_edge(START, "validate")
        builder.add_edge("validate", "order_seller")
        builder.add_edge("validate", "payment")
        builder.add_edge("validate", "delivery")
        builder.add_edge(["order_seller", "payment", "delivery"], "collect")
        builder.add_conditional_edges(
            "collect",
            self._route_after_collect,
            {"policy": "policy", "retry_domains": "retry_domains", "fail": "fail"},
        )
        builder.add_edge("retry_domains", "collect")
        builder.add_edge("policy", "draft")
        builder.add_edge("draft", "verify")
        builder.add_conditional_edges(
            "verify",
            self._route_after_verify,
            {
                "write": "write",
                "retry_domains": "retry_domains",
                "policy": "policy",
                "draft": "draft",
                "verify": "verify",
                "fail": "fail",
            },
        )
        builder.add_edge("write", END)
        builder.add_edge("fail", END)
        return builder.compile(name="olist-dispute-coordinator")

    async def _validate_node(self, state: CoordinatorGraphState) -> dict[str, Any]:
        try:
            case = CaseInput.model_validate(state["raw_case"])
        except ValidationError as exc:
            raise CoordinationFailure(
                [
                    AgentError(
                        code="INVALID_CASE_SCHEMA",
                        path=".".join(str(part) for part in error["loc"]),
                        message=error["msg"],
                        source=state["source_filename"],
                        retryable=False,
                        retry_target=AgentName.COORDINATOR,
                    )
                    for error in exc.errors()
                ]
            ) from exc

        expected_filename = f"{case.case_id}.json"
        if Path(state["source_filename"]).name != expected_filename:
            raise CoordinationFailure(
                [
                    AgentError(
                        code="CASE_FILENAME_MISMATCH",
                        path="case_id",
                        message=f"expected filename {expected_filename}",
                        source=state["source_filename"],
                        retryable=False,
                        retry_target=AgentName.COORDINATOR,
                    )
                ]
            )
        if not state["run_id"]:
            raise CoordinationFailure(
                [
                    AgentError(
                        code="INVALID_RUN_ID",
                        path="run_id",
                        message="run_id must not be blank",
                        source="coordinator",
                    )
                ]
            )

        registry_key = (state["run_id"], case.case_id)
        async with self._seen_lock:
            if registry_key in self._seen_cases:
                raise CoordinationFailure(
                    [
                        AgentError(
                            code="DUPLICATE_CASE_IN_RUN",
                            path="case_id",
                            message=f"{case.case_id} was already processed in this run",
                            source=state["source_filename"],
                        )
                    ]
                )
            self._seen_cases.add(registry_key)

        update: dict[str, Any] = {"case": case, "phase": CoordinatorPhase.VALIDATED}
        await self._emit({**state, **update}, "case_validated", "success")
        return update

    async def _order_seller_node(self, state: CoordinatorGraphState) -> dict[str, Any]:
        return await self._domain_node(
            state,
            AgentName.ORDER_SELLER,
            {
                "lookup_order_id": state["case"].customer_request.claimed_order_id,
                "include_product_validation": False,
            },
        )

    async def _payment_node(self, state: CoordinatorGraphState) -> dict[str, Any]:
        return await self._domain_node(
            state,
            AgentName.PAYMENT,
            {
                "lookup_order_id": state["case"].customer_request.claimed_order_id,
                "reconciliation_tolerance_brl": float(self._config.payment_tolerance_brl),
            },
        )

    async def _delivery_node(self, state: CoordinatorGraphState) -> dict[str, Any]:
        return await self._domain_node(
            state,
            AgentName.DELIVERY,
            {"lookup_order_id": state["case"].customer_request.claimed_order_id},
        )

    async def _domain_node(
        self,
        state: CoordinatorGraphState,
        agent_name: AgentName,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        result = await self._invoke_agent(state, agent_name, payload)
        return {
            "domain_results": {agent_name.value: result},
        }

    async def _collect_node(self, state: CoordinatorGraphState) -> dict[str, Any]:
        required = {
            AgentName.ORDER_SELLER.value,
            AgentName.PAYMENT.value,
            AgentName.DELIVERY.value,
        }
        missing = sorted(required - state["domain_results"].keys())
        if missing:
            raise CoordinationFailure(
                [
                    AgentError(
                        code="MISSING_DOMAIN_RESULT",
                        message=f"missing domain results: {', '.join(missing)}",
                        source="coordinator",
                    )
                ]
            )

        conflicts = self._find_total_conflicts(state["domain_results"])
        if conflicts:
            count = state.get("domain_conflict_count", 0) + 1
            update: dict[str, Any] = {
                "domain_conflict_count": count,
                "retry_targets": [AgentName.ORDER_SELLER, AgentName.PAYMENT],
                "errors": conflicts,
            }
            await self._emit(
                {**state, **update},
                "domain_conflict",
                "failed",
                output_summary={"error_codes": [error.code for error in conflicts]},
                handoff_to="retry_domains",
            )
            return update

        bundle = self._build_evidence_bundle(state)
        handoffs = {
            **state.get("handoffs", {}),
            AgentName.ORDER_SELLER.value: AgentStatus.SUCCESS.value,
            AgentName.PAYMENT.value: AgentStatus.SUCCESS.value,
            AgentName.DELIVERY.value: AgentStatus.SUCCESS.value,
        }
        update = {
            "bundle": bundle,
            "phase": CoordinatorPhase.COLLECTED,
            "retry_targets": [],
            "errors": [],
            "handoffs": handoffs,
        }
        await self._emit(
            {**state, **update},
            "handoff_sent",
            "success",
            output_summary={
                "bundle_version": bundle.bundle_version,
                "bundle_digest": bundle.bundle_digest,
            },
            handoff_to=AgentName.POLICY.value,
        )
        return update

    def _route_after_collect(self, state: CoordinatorGraphState) -> str:
        if not state.get("errors"):
            return "policy"
        if state.get("domain_conflict_count", 0) <= self._config.max_domain_conflict_retries:
            return "retry_domains"
        return "fail"

    async def _retry_domains_node(self, state: CoordinatorGraphState) -> dict[str, Any]:
        domain_targets = [
            target
            for target in state.get("retry_targets", [])
            if target in {AgentName.ORDER_SELLER, AgentName.PAYMENT, AgentName.DELIVERY}
        ]
        if not domain_targets:
            raise CoordinationFailure(
                [
                    AgentError(
                        code="INVALID_RETRY_TARGET",
                        message="domain retry requested without a domain target",
                        source="coordinator",
                    )
                ]
            )

        payloads: dict[AgentName, dict[str, Any]] = {
            AgentName.ORDER_SELLER: {
                "lookup_order_id": state["case"].customer_request.claimed_order_id,
                "include_product_validation": False,
            },
            AgentName.PAYMENT: {
                "lookup_order_id": state["case"].customer_request.claimed_order_id,
                "reconciliation_tolerance_brl": float(self._config.payment_tolerance_brl),
            },
            AgentName.DELIVERY: {
                "lookup_order_id": state["case"].customer_request.claimed_order_id
            },
        }
        results = await asyncio.gather(
            *(self._invoke_agent(state, target, payloads[target]) for target in domain_targets)
        )
        return {
            "domain_results": {
                target.value: result for target, result in zip(domain_targets, results, strict=True)
            },
            "errors": [],
        }

    async def _policy_node(self, state: CoordinatorGraphState) -> dict[str, Any]:
        bundle = state["bundle"]
        result = await self._invoke_agent(
            state,
            AgentName.POLICY,
            {
                "evidence_bundle": bundle.model_dump(mode="json"),
                "policy_version": POLICY_VERSION,
            },
        )
        try:
            decision = PolicyDecision.model_validate(result.facts)
        except ValidationError as exc:
            raise CoordinationFailure(
                [self._contract_error("INVALID_POLICY_DECISION", exc, AgentName.POLICY)]
            ) from exc
        if (
            decision.bundle_version != bundle.bundle_version
            or decision.bundle_digest != bundle.bundle_digest
        ):
            raise CoordinationFailure(
                [
                    AgentError(
                        code="STALE_POLICY_DECISION",
                        message="policy decision does not match the current evidence bundle",
                        source=AgentName.POLICY.value,
                        retryable=False,
                        retry_target=AgentName.POLICY,
                    )
                ]
            )

        handoffs = {**state.get("handoffs", {}), AgentName.POLICY.value: "success"}
        update: dict[str, Any] = {
            "policy_result": result,
            "policy_decision": decision,
            "phase": CoordinatorPhase.POLICY_DECIDED,
            "handoffs": handoffs,
            "errors": [],
        }
        await self._emit(
            {**state, **update},
            "policy_decided",
            "success",
            output_summary={
                "primary_issue": decision.primary_issue.value,
                "matched_rule_priority": decision.matched_rule_priority,
                "confidence": decision.confidence,
                "confidence_basis": decision.confidence_basis,
            },
            handoff_to="draft",
        )
        return update

    async def _draft_node(self, state: CoordinatorGraphState) -> dict[str, Any]:
        draft = self._build_final_output(state)
        version = state.get("draft_version", 0) + 1
        digest = _canonical_digest(draft.model_dump(mode="json"))
        update: dict[str, Any] = {
            "draft": draft,
            "draft_version": version,
            "draft_digest": digest,
            "phase": CoordinatorPhase.DRAFTED,
            "errors": [],
        }
        await self._emit(
            {**state, **update},
            "draft_created",
            "success",
            output_summary={"draft_version": version, "draft_digest": digest},
            handoff_to=AgentName.VERIFIER.value,
        )
        return update

    async def _verify_node(self, state: CoordinatorGraphState) -> dict[str, Any]:
        round_number = state.get("verification_round", 0) + 1
        result = await self._invoke_agent(
            state,
            AgentName.VERIFIER,
            {
                "case_input": state["case"].model_dump(mode="json"),
                "agent_results": {
                    name: value.model_dump(mode="json")
                    for name, value in state["domain_results"].items()
                },
                "evidence_bundle": state["bundle"].model_dump(mode="json"),
                "policy_decision": state["policy_decision"].model_dump(mode="json"),
                "draft_output": state["draft"].model_dump(mode="json"),
                "draft_version": state["draft_version"],
                "draft_digest": state["draft_digest"],
            },
        )
        try:
            verification = VerificationResult.model_validate(result.facts)
        except ValidationError as exc:
            raise CoordinationFailure(
                [self._contract_error("INVALID_VERIFICATION_RESULT", exc, AgentName.VERIFIER)]
            ) from exc

        if (
            verification.draft_version != state["draft_version"]
            or verification.draft_digest != state["draft_digest"]
        ):
            raise CoordinationFailure(
                [
                    AgentError(
                        code="STALE_VERIFICATION_RESULT",
                        message="verifier result does not match the current draft",
                        source=AgentName.VERIFIER.value,
                        retryable=False,
                        retry_target=AgentName.VERIFIER,
                    )
                ]
            )

        targets: list[AgentName] = _ordered_unique(
            error.retry_target for error in verification.errors
        )
        handoffs = {
            **state.get("handoffs", {}),
            AgentName.VERIFIER.value: verification.verdict,
        }
        phase = (
            CoordinatorPhase.VERIFIED
            if verification.verdict == "PASS"
            else CoordinatorPhase.VERIFYING
        )
        update: dict[str, Any] = {
            "verification": verification,
            "verification_round": round_number,
            "retry_targets": targets,
            "phase": phase,
            "handoffs": handoffs,
            "errors": verification.errors,
        }
        await self._emit(
            {**state, **update},
            "verification_completed",
            "success" if verification.verdict == "PASS" else "failed",
            input_refs={
                "agent": AgentName.VERIFIER.value,
                "task_id": result.task_id,
                "attempt": result.attempt,
                "draft_version": state["draft_version"],
                "draft_digest": state["draft_digest"],
            },
            output_summary={
                "verdict": verification.verdict,
                "draft_version": verification.draft_version,
                "error_codes": [error.code for error in verification.errors],
                "error_details": [
                    {
                        "code": error.code,
                        "path": error.path,
                        "message": error.message,
                        "retry_target": error.retry_target.value,
                    }
                    for error in verification.errors
                ],
            },
            handoff_to="write" if verification.verdict == "PASS" else "retry",
        )
        return update

    def _route_after_verify(self, state: CoordinatorGraphState) -> str:
        verification = state["verification"]
        if verification.verdict == "PASS":
            return "write"
        if state.get("verification_round", 0) >= self._config.max_verification_rounds:
            return "fail"
        if any(not error.retryable for error in verification.errors):
            return "fail"

        targets = set(state.get("retry_targets", []))
        domain_targets = {
            AgentName.ORDER_SELLER,
            AgentName.PAYMENT,
            AgentName.DELIVERY,
        }
        if targets & domain_targets:
            return "retry_domains"
        if AgentName.POLICY in targets:
            return "policy"
        if AgentName.COORDINATOR in targets:
            return "draft"
        if AgentName.VERIFIER in targets:
            return "verify"
        return "fail"

    async def _write_node(self, state: CoordinatorGraphState) -> dict[str, Any]:
        filename = f"{state['case'].case_id}.json"
        output_path = await _maybe_await(
            self._output_store.write(filename, state["draft"].model_dump(mode="json"))
        )
        update: dict[str, Any] = {
            "phase": CoordinatorPhase.WRITTEN,
            "output_path": str(output_path),
            "errors": [],
        }
        await self._emit(
            {**state, **update},
            "output_written",
            "success",
            output_summary={
                "path": str(output_path),
                "draft_digest": state["draft_digest"],
            },
        )
        return update

    async def _fail_node(self, state: CoordinatorGraphState) -> dict[str, Any]:
        errors = state.get("errors") or [
            AgentError(
                code="COORDINATION_FAILED",
                message="coordinator reached a terminal failure",
                source="coordinator",
            )
        ]
        update: dict[str, Any] = {"phase": CoordinatorPhase.FAILED, "errors": errors}
        await self._emit(
            {**state, **update},
            "case_failed",
            "failed",
            output_summary={"error_codes": [error.code for error in errors]},
        )
        return update

    async def _invoke_agent(
        self,
        state: Mapping[str, Any],
        agent_name: AgentName,
        payload: dict[str, Any],
    ) -> AgentResult:
        case_value = state["case"]
        if not isinstance(case_value, CaseInput):
            raise TypeError("coordinator state is missing a validated case")
        case = case_value
        errors: list[AgentError] = []
        for attempt in range(1, self._config.max_agent_attempts + 1):
            task = AgentTask(
                contract_version="1.0",
                run_id=state["run_id"],
                correlation_id=state["correlation_id"],
                task_id=self._id_factory(),
                attempt=attempt,
                case_id=case.case_id,
                order_id=case.customer_request.claimed_order_id,
                policy_version="EC_POLICY_V1",
                requested_at=self._clock(),
                payload=payload,
            )
            await self._emit(
                state,
                "task_dispatched",
                "success",
                input_refs={
                    "agent": agent_name.value,
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "payload_digest": _canonical_digest(payload),
                },
                handoff_to=agent_name.value,
            )
            started = time.perf_counter()
            try:
                raw_result = await asyncio.wait_for(
                    _maybe_await(self._agents[agent_name].run(task)),
                    timeout=self._config.agent_timeout_seconds,
                )
                result = (
                    raw_result
                    if isinstance(raw_result, AgentResult)
                    else AgentResult.model_validate(raw_result)
                )
                self._validate_result_identity(result, task, agent_name)
            except TimeoutError:
                errors = [
                    AgentError(
                        code="AGENT_TIMEOUT",
                        message=f"{agent_name.value} exceeded timeout",
                        source=agent_name.value,
                        retryable=True,
                        retry_target=agent_name,
                    )
                ]
            except (ValidationError, CoordinationFailure) as exc:
                if isinstance(exc, CoordinationFailure):
                    errors = exc.errors
                else:
                    errors = [self._contract_error("INVALID_AGENT_RESULT", exc, agent_name)]
            except Exception as exc:
                errors = [
                    AgentError(
                        code="AGENT_INTERNAL_ERROR",
                        message=f"{type(exc).__name__}: {exc}",
                        source=agent_name.value,
                        retryable=True,
                        retry_target=agent_name,
                    )
                ]
            else:
                elapsed_ms = round((time.perf_counter() - started) * 1_000, 2)
                await self._emit(
                    state,
                    "agent_completed",
                    result.status.value,
                    input_refs={
                        "agent": agent_name.value,
                        "task_id": task.task_id,
                        "attempt": attempt,
                        "payload_digest": _canonical_digest(payload),
                    },
                    output_summary={
                        "agent": agent_name.value,
                        "result_digest": _canonical_digest(result.model_dump(mode="json")),
                        "duration_ms": elapsed_ms,
                        "error_codes": [error.code for error in result.errors],
                        "api_models": sorted(
                            {
                                str(warning["model"])
                                for warning in result.warnings
                                if isinstance(warning, dict) and warning.get("model")
                            }
                        ),
                    },
                    handoff_to=AgentName.COORDINATOR.value,
                )
                if result.status == AgentStatus.SUCCESS:
                    return result
                errors = result.errors

            if attempt >= self._config.max_agent_attempts or any(
                not error.retryable for error in errors
            ):
                raise CoordinationFailure(errors)

            await self._emit(
                state,
                "agent_retry_scheduled",
                "retry",
                input_refs={
                    "agent": agent_name.value,
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "payload_digest": _canonical_digest(payload),
                },
                output_summary={
                    "agent": agent_name.value,
                    "next_attempt": attempt + 1,
                    "error_codes": [error.code for error in errors],
                },
                handoff_to=agent_name.value,
            )

        raise CoordinationFailure(errors)

    def _validate_result_identity(
        self, result: AgentResult, task: AgentTask, expected_agent: AgentName
    ) -> None:
        mismatches: list[str] = []
        for name in (
            "contract_version",
            "run_id",
            "correlation_id",
            "task_id",
            "attempt",
            "case_id",
            "order_id",
            "policy_version",
        ):
            if getattr(result, name) != getattr(task, name):
                mismatches.append(name)
        if result.agent_name != expected_agent:
            mismatches.append("agent_name")
        if mismatches:
            raise CoordinationFailure(
                [
                    AgentError(
                        code="HANDOFF_IDENTITY_MISMATCH",
                        path=",".join(mismatches),
                        message="agent result identity does not match its task",
                        source=expected_agent.value,
                        retryable=False,
                        retry_target=expected_agent,
                    )
                ]
            )

    def _find_total_conflicts(self, results: Mapping[str, AgentResult]) -> list[AgentError]:
        order_facts = results[AgentName.ORDER_SELLER.value].facts
        payment_facts = results[AgentName.PAYMENT.value].facts
        comparisons = (
            ("item_total_brl", "item_total_brl_check"),
            ("freight_total_brl", "freight_total_brl_check"),
        )
        errors: list[AgentError] = []
        for order_key, payment_key in comparisons:
            try:
                left = _money_decimal(order_facts[order_key])
                right = _money_decimal(payment_facts[payment_key])
            except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                errors.append(
                    AgentError(
                        code="MISSING_CRITICAL_FACT",
                        path=f"{order_key}/{payment_key}",
                        message=str(exc),
                        source="evidence_bundle",
                        retryable=True,
                        retry_target=AgentName.ORDER_SELLER,
                    )
                )
                continue
            if left != right:
                errors.append(
                    AgentError(
                        code="DOMAIN_TOTAL_CONFLICT",
                        path=f"{order_key}/{payment_key}",
                        message=f"domain totals differ: {left} != {right}",
                        source="evidence_bundle",
                        retryable=True,
                        retry_target=AgentName.PAYMENT,
                    )
                )
        return errors

    def _build_evidence_bundle(self, state: CoordinatorGraphState) -> EvidenceBundle:
        results = state["domain_results"]
        order_result = results[AgentName.ORDER_SELLER.value]
        payment_result = results[AgentName.PAYMENT.value]
        delivery_result = results[AgentName.DELIVERY.value]
        ordered_results = [order_result, payment_result, delivery_result]
        entity_candidates = EntityCandidates(
            order_ids=_merge_unique_strings(
                result.entity_candidates.order_ids for result in ordered_results
            ),
            item_ids=_merge_unique_strings(
                result.entity_candidates.item_ids for result in ordered_results
            ),
            seller_ids=_merge_unique_strings(
                result.entity_candidates.seller_ids for result in ordered_results
            ),
            payment_ids=_merge_unique_strings(
                result.entity_candidates.payment_ids for result in ordered_results
            ),
        )
        evidence_candidates = _merge_unique_strings(
            result.evidence_candidates for result in ordered_results
        )
        warnings: list[WarningValue] = []
        for result in ordered_results:
            warnings.extend(result.warnings)
        version = state.get("bundle", None)
        bundle_version = version.bundle_version + 1 if version else 1
        payload: dict[str, Any] = {
            "contract_version": CONTRACT_VERSION,
            "run_id": state["run_id"],
            "correlation_id": state["correlation_id"],
            "case_id": state["case"].case_id,
            "order_id": state["case"].customer_request.claimed_order_id,
            "policy_version": POLICY_VERSION,
            "bundle_version": bundle_version,
            "source_status": {name: "success" for name in sorted(results)},
            "order_facts": dict(order_result.facts.get("order", {})),
            "item_seller_facts": order_result.facts,
            "payment_facts": payment_result.facts,
            "delivery_facts": delivery_result.facts,
            "entity_candidates": entity_candidates.model_dump(mode="json"),
            "evidence_candidates": evidence_candidates,
            "warnings": warnings,
        }
        payload["bundle_digest"] = _canonical_digest(payload)
        return EvidenceBundle.model_validate(payload)

    def _build_final_output(self, state: CoordinatorGraphState) -> FinalOutput:
        decision = state["policy_decision"]
        bundle = state["bundle"]
        self._validate_policy_selections(decision, bundle)
        has_item_rows = bool(bundle.item_seller_facts.get("items"))
        item_total = (
            _money_float(bundle.item_seller_facts["item_total_brl"]) if has_item_rows else 0.0
        )
        freight_total = (
            _money_float(bundle.item_seller_facts["freight_total_brl"]) if has_item_rows else 0.0
        )
        payment_total = _money_float(bundle.payment_facts["payment_total_brl"])
        refund = _money_float(decision.recommended_refund_brl)
        return FinalOutput(
            case_id=state["case"].case_id,
            assessment=Assessment(
                primary_issue=decision.primary_issue,
                case_status=decision.case_status,
                confidence=decision.confidence,
            ),
            affected_entities=AffectedEntities(
                order_ids=decision.selected_entities.order_ids,
                item_ids=decision.selected_entities.item_ids if has_item_rows else [],
                seller_ids=decision.selected_entities.seller_ids if has_item_rows else [],
                payment_ids=decision.selected_entities.payment_ids,
            ),
            root_cause_analysis=RootCauseAnalysis(
                ranked_causes=decision.ranked_causes,
                responsible_parties=decision.responsible_parties,
            ),
            evidence_ids=decision.selected_evidence_ids,
            financial_resolution=FinancialResolution(
                currency="BRL",
                item_total_brl=item_total,
                freight_total_brl=freight_total,
                payment_total_brl=payment_total,
                recommended_refund_brl=refund,
            ),
            resolution_actions=decision.resolution_actions,
        )

    def _validate_policy_selections(self, decision: PolicyDecision, bundle: EvidenceBundle) -> None:
        for field_name in ("order_ids", "item_ids", "seller_ids", "payment_ids"):
            selected = getattr(decision.selected_entities, field_name)
            expected = getattr(bundle.entity_candidates, field_name)[:5]
            if selected != expected:
                raise CoordinationFailure(
                    [
                        AgentError(
                            code="INCOMPLETE_ENTITY_SELECTION",
                            path=f"selected_entities.{field_name}",
                            message="policy must select every expected entity ID in stable order",
                            source=AgentName.POLICY.value,
                            retryable=True,
                            retry_target=AgentName.POLICY,
                        )
                    ]
                )

        candidate_evidence = set(bundle.evidence_candidates)
        cause_codes = {cause.cause_code.value for cause in decision.ranked_causes}
        for evidence_id in decision.selected_evidence_ids:
            if evidence_id.startswith("policy:"):
                if evidence_id.removeprefix("policy:") not in cause_codes:
                    raise CoordinationFailure(
                        [
                            AgentError(
                                code="INVALID_POLICY_EVIDENCE",
                                path="selected_evidence_ids",
                                message="policy evidence does not match a ranked cause",
                                source=AgentName.POLICY.value,
                                retryable=True,
                                retry_target=AgentName.POLICY,
                            )
                        ]
                    )
            elif evidence_id not in candidate_evidence:
                raise CoordinationFailure(
                    [
                        AgentError(
                            code="INVALID_EVIDENCE",
                            path="selected_evidence_ids",
                            message="selected evidence is absent from the evidence bundle",
                            source=AgentName.POLICY.value,
                            retryable=True,
                            retry_target=AgentName.POLICY,
                        )
                    ]
                )

    def _contract_error(self, code: str, exc: ValidationError, target: AgentName) -> AgentError:
        first = exc.errors()[0]
        return AgentError(
            code=code,
            path=".".join(str(part) for part in first["loc"]),
            message=first["msg"],
            source=target.value,
            retryable=False,
            retry_target=target,
        )

    async def _emit(
        self,
        state: Mapping[str, Any],
        event_type: str,
        status: str,
        *,
        input_refs: Mapping[str, Any] | None = None,
        output_summary: Mapping[str, Any] | None = None,
        handoff_to: str | None = None,
    ) -> None:
        if self._trace_sink is None:
            return
        case_value = state.get("case")
        case = case_value if isinstance(case_value, CaseInput) else None
        resolved_input_refs = self._lineage_refs(state)
        resolved_input_refs.update(dict(input_refs or {}))
        event = {
            "timestamp": self._clock().isoformat(),
            "run_id": state["run_id"],
            "correlation_id": state["correlation_id"],
            "case_id": case.case_id if case else state.get("raw_case", {}).get("case_id"),
            "agent": AgentName.COORDINATOR.value,
            "event_type": event_type,
            "status": status,
            "phase": str(state.get("phase", CoordinatorPhase.RECEIVED)),
            "input_refs": resolved_input_refs,
            "output_summary": dict(output_summary or {}),
            "handoff_to": handoff_to,
        }
        await _maybe_await(self._trace_sink.emit(event))

    @staticmethod
    def _lineage_refs(state: Mapping[str, Any]) -> dict[str, Any]:
        refs: dict[str, Any] = {}
        source_filename = state.get("source_filename")
        if isinstance(source_filename, str) and source_filename:
            refs["source_filename"] = Path(source_filename).name

        case_value = state.get("case")
        if isinstance(case_value, CaseInput):
            refs["input_case_id"] = case_value.case_id
            refs["order_id"] = case_value.customer_request.claimed_order_id
        else:
            raw_case = state.get("raw_case")
            if isinstance(raw_case, Mapping):
                raw_case_id = raw_case.get("case_id")
                if isinstance(raw_case_id, str) and raw_case_id:
                    refs["input_case_id"] = raw_case_id
                customer_request = raw_case.get("customer_request")
                if isinstance(customer_request, Mapping):
                    order_id = customer_request.get("claimed_order_id")
                    if isinstance(order_id, str) and order_id:
                        refs["order_id"] = order_id

        domain_results = state.get("domain_results")
        if isinstance(domain_results, Mapping):
            domain_tasks = {
                str(name): {"task_id": result.task_id, "attempt": result.attempt}
                for name, result in domain_results.items()
                if isinstance(result, AgentResult)
            }
            if domain_tasks:
                refs["domain_tasks"] = domain_tasks

        bundle = state.get("bundle")
        if isinstance(bundle, EvidenceBundle):
            refs["evidence_bundle"] = {
                "version": bundle.bundle_version,
                "digest": bundle.bundle_digest,
            }

        policy_result = state.get("policy_result")
        if isinstance(policy_result, AgentResult):
            refs["policy_task"] = {
                "task_id": policy_result.task_id,
                "attempt": policy_result.attempt,
            }

        draft_version = state.get("draft_version")
        draft_digest = state.get("draft_digest")
        if isinstance(draft_version, int) and isinstance(draft_digest, str):
            refs["draft"] = {"version": draft_version, "digest": draft_digest}
        return refs

    def _result_from_state(self, state: Mapping[str, Any]) -> CoordinatorResult:
        phase = state.get("phase", CoordinatorPhase.FAILED)
        success = phase == CoordinatorPhase.WRITTEN
        case_value = state.get("case")
        case = case_value if isinstance(case_value, CaseInput) else None
        return CoordinatorResult(
            success=success,
            phase=phase,
            run_id=state["run_id"],
            correlation_id=state["correlation_id"],
            case_id=case.case_id if case else state.get("raw_case", {}).get("case_id"),
            handoffs=state.get("handoffs", {}),
            final_output=state.get("draft") if success else None,
            output_path=state.get("output_path"),
            errors=state.get("errors", []),
        )


async def _maybe_await[T](value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


def _canonical_digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _money_decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise TypeError("boolean is not a money value")
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("money value must be finite and non-negative")
    return amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _money_float(value: Any) -> float:
    return float(_money_decimal(value))


def _merge_unique_strings(groups: Iterable[Iterable[str]]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            if value not in seen:
                seen.add(value)
                merged.append(value)
    return merged


def _ordered_unique[T: Hashable](values: Iterable[T]) -> list[T]:
    result: list[T] = []
    seen: set[T] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
