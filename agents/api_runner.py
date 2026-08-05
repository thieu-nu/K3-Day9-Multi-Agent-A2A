from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from agents.coordinator import (
    AgentError,
    AgentName,
    AgentResult,
    AgentRunner,
    AgentStatus,
    AgentTask,
    EntityCandidates,
    PolicyDecision,
    VerificationResult,
    _maybe_await,
)
from utils.llm_client import QWEN_MODEL, QWEN_PROVIDER, TogetherStructuredClient


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


ShortText = Annotated[str, Field(min_length=1, max_length=200)]
Identifier = Annotated[str, Field(min_length=1, max_length=150)]


class ApiEntityCandidates(ApiModel):
    order_ids: list[Identifier] = Field(max_length=20)
    item_ids: list[Identifier] = Field(max_length=20)
    seller_ids: list[Identifier] = Field(max_length=20)
    payment_ids: list[Identifier] = Field(max_length=20)


class ApiSelectedEntities(ApiModel):
    order_ids: list[Identifier] = Field(max_length=5)
    item_ids: list[Identifier] = Field(max_length=5)
    seller_ids: list[Identifier] = Field(max_length=5)
    payment_ids: list[Identifier] = Field(max_length=5)


class OrderRecord(ApiModel):
    order_id: str
    customer_id: str
    order_status: str
    order_purchase_timestamp: str | None
    order_approved_at: str | None
    order_delivered_carrier_date: str | None
    order_delivered_customer_date: str | None
    order_estimated_delivery_date: str | None


class OrderItemFact(ApiModel):
    order_item_id: int
    product_id: str | None
    seller_id: str | None
    shipping_limit_date: str | None
    price_brl: float = Field(ge=0, allow_inf_nan=False)
    freight_value_brl: float = Field(ge=0, allow_inf_nan=False)
    handoff_after_limit: bool | None


class OrderSellerFacts(ApiModel):
    order_found: Literal[True]
    order: OrderRecord
    items: list[OrderItemFact]
    item_total_brl: float = Field(ge=0, allow_inf_nan=False)
    freight_total_brl: float = Field(ge=0, allow_inf_nan=False)
    violating_seller_ids: list[str]
    missing_seller_ids: list[str]


class PaymentFact(ApiModel):
    payment_sequential: int = Field(ge=1)
    payment_type: str | None
    payment_installments: int = Field(ge=1)
    payment_value_brl: float = Field(ge=0, allow_inf_nan=False)


class PaymentFacts(ApiModel):
    payments: list[PaymentFact]
    payment_count: int = Field(ge=0)
    payment_total_brl: float = Field(ge=0, allow_inf_nan=False)
    item_total_brl_check: float = Field(ge=0, allow_inf_nan=False)
    freight_total_brl_check: float = Field(ge=0, allow_inf_nan=False)
    expected_total_brl: float = Field(ge=0, allow_inf_nan=False)
    difference_brl: float = Field(ge=0, allow_inf_nan=False)
    is_reconciled: bool
    is_split_payment: bool


class SellerHandoffFact(ApiModel):
    order_item_id: int = Field(ge=1)
    seller_id: str | None
    shipping_limit_date: str | None
    carrier_date: str | None
    handoff_after_limit: bool | None


class DeliveryFacts(ApiModel):
    delivery_timestamp_available: bool
    delivered_after_estimate: bool
    delivery_within_estimate: bool
    seller_handoffs: list[SellerHandoffFact]
    attribution_candidate: Literal[
        "seller", "logistics_provider", "none", "not_applicable", "unknown"
    ]
    responsible_seller_candidates: list[str]
    root_cause_candidates: list[str]


class ApiRankedCause(ApiModel):
    cause_code: Literal[
        "SELLER_HANDOFF_AFTER_LIMIT",
        "CARRIER_DELIVERED_AFTER_ESTIMATE",
        "ORDER_CANCELED_AFTER_PAYMENT",
        "ORDER_UNAVAILABLE_AFTER_PAYMENT",
        "MULTIPLE_PAYMENTS_RECONCILED",
        "DELIVERY_WITHIN_ESTIMATE",
    ]
    rank: int = Field(ge=1, le=3)


class ApiResponsibleParty(ApiModel):
    party_type: Literal["seller", "platform", "logistics_provider"]
    party_id: str


class ApiExcludedRule(ApiModel):
    priority: int = Field(ge=1, le=6)
    reason_code: str


class PolicyDecisionApi(ApiModel):
    bundle_version: int = Field(ge=1)
    bundle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched_rule_priority: int = Field(ge=1, le=6)
    primary_issue: Literal[
        "canceled_order_paid",
        "unavailable_order_paid",
        "late_delivery_seller",
        "late_delivery_logistics",
        "valid_split_payment",
        "unsupported_late_claim",
    ]
    case_status: Literal["action_required", "no_action"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    confidence_basis: list[str]
    selected_entities: ApiSelectedEntities
    ranked_causes: list[ApiRankedCause] = Field(min_length=1, max_length=3)
    responsible_parties: list[ApiResponsibleParty] = Field(max_length=3)
    recommended_refund_brl: float = Field(ge=0, allow_inf_nan=False)
    resolution_actions: list[
        Literal[
            "issue_full_refund",
            "refund_freight",
            "explain_valid_split_payment",
            "reject_late_refund",
        ]
    ] = Field(min_length=1, max_length=5)
    selected_evidence_ids: list[str] = Field(min_length=1, max_length=10)
    excluded_higher_priority_rules: list[ApiExcludedRule]


class ApiVerificationChecks(ApiModel):
    schema_check: bool = Field(alias="schema")
    identity: bool
    entities: bool
    evidence: bool
    financials: bool
    policy: bool
    limits: bool


class ApiRecomputedValues(ApiModel):
    item_total_brl: float = Field(ge=0, allow_inf_nan=False)
    freight_total_brl: float = Field(ge=0, allow_inf_nan=False)
    payment_total_brl: float = Field(ge=0, allow_inf_nan=False)
    recommended_refund_brl: float = Field(ge=0, allow_inf_nan=False)


class ApiVerificationError(ApiModel):
    code: ShortText
    path: Annotated[str, Field(max_length=200)]
    message: ShortText
    source: Annotated[str, Field(max_length=200)]
    retryable: bool
    retry_target: AgentName


class VerificationResultApi(ApiModel):
    verdict: Literal["PASS", "FAIL"]
    draft_version: int = Field(ge=1)
    draft_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: ApiVerificationChecks
    recomputed_values: ApiRecomputedValues
    errors: list[ApiVerificationError] = Field(max_length=10)
    warnings: list[ShortText] = Field(max_length=5)


class ApiGeneratedResponse[FactsT: BaseModel](ApiModel):
    agent_name: AgentName
    task_id: str = Field(min_length=1)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    facts: FactsT
    entity_candidates: ApiEntityCandidates
    evidence_candidates: list[Identifier] = Field(max_length=30)
    warnings: list[ShortText] = Field(default_factory=list, max_length=5)


API_FACT_MODELS: dict[AgentName, type[BaseModel]] = {
    AgentName.ORDER_SELLER: OrderSellerFacts,
    AgentName.PAYMENT: PaymentFacts,
    AgentName.DELIVERY: DeliveryFacts,
    AgentName.POLICY: PolicyDecisionApi,
    AgentName.VERIFIER: VerificationResultApi,
}

RESULT_FACT_MODELS: dict[AgentName, type[BaseModel]] = {
    AgentName.ORDER_SELLER: OrderSellerFacts,
    AgentName.PAYMENT: PaymentFacts,
    AgentName.DELIVERY: DeliveryFacts,
    AgentName.POLICY: PolicyDecision,
    AgentName.VERIFIER: VerificationResult,
}

RESPONSE_MODELS: dict[AgentName, type[ApiGeneratedResponse[Any]]] = {
    AgentName.ORDER_SELLER: cast(
        type[ApiGeneratedResponse[Any]], ApiGeneratedResponse[OrderSellerFacts]
    ),
    AgentName.PAYMENT: cast(type[ApiGeneratedResponse[Any]], ApiGeneratedResponse[PaymentFacts]),
    AgentName.DELIVERY: cast(type[ApiGeneratedResponse[Any]], ApiGeneratedResponse[DeliveryFacts]),
    AgentName.POLICY: cast(
        type[ApiGeneratedResponse[Any]], ApiGeneratedResponse[PolicyDecisionApi]
    ),
    AgentName.VERIFIER: cast(
        type[ApiGeneratedResponse[Any]], ApiGeneratedResponse[VerificationResultApi]
    ),
}


class ApiGeneratedAgent:
    """Uses deterministic tools for context and Qwen for the final typed agent result."""

    def __init__(
        self,
        *,
        agent_name: AgentName,
        tool_runner: AgentRunner,
        client: TogetherStructuredClient,
        max_tokens: int = 2_048,
    ) -> None:
        if agent_name not in API_FACT_MODELS:
            raise ValueError(f"API generation is unsupported for {agent_name.value}")
        self._agent_name = agent_name
        self._tool_runner = tool_runner
        self._client = client
        self._max_tokens = max_tokens

    async def run(self, task: AgentTask) -> AgentResult:
        # The tool runner is authoritative for database lookups and ordered policy rules.
        # Qwen is called only after that Python evaluation succeeds.
        raw_tool_result = await _maybe_await(self._tool_runner.run(task))
        tool_result = (
            raw_tool_result
            if isinstance(raw_tool_result, AgentResult)
            else AgentResult.model_validate(raw_tool_result)
        )
        if tool_result.status.value != "success":
            return tool_result

        tool_context = tool_result.model_dump(mode="json")
        if self._agent_name == AgentName.POLICY:
            policy_facts = dict(tool_context["facts"])
            policy_facts.pop("confidence", None)
            policy_facts.pop("confidence_basis", None)
            tool_context["facts"] = policy_facts
        source = {
            "task": task.model_dump(mode="json"),
            "tool_result": tool_context,
        }
        source_digest = self._digest(source)
        api_facts_model = API_FACT_MODELS[self._agent_name]
        result_facts_model = RESULT_FACT_MODELS[self._agent_name]
        response_model = RESPONSE_MODELS[self._agent_name]
        generated = await self._client.complete_structured(
            system_prompt=(
                f"You are the {self._agent_name.value} agent in an e-commerce dispute system. "
                "The tool_result contains trusted output from your CSV/database and deterministic "
                "calculation tools. Produce your own final structured agent response from that "
                "tool context. Preserve every ID, timestamp, boolean, enum, and monetary value; "
                "do not invent rows. For the policy agent, Python has already applied the ordered "
                "EC_POLICY_V1 table. You MUST preserve bundle_version, bundle_digest, "
                "matched_rule_priority, primary_issue, case_status, ranked_causes, "
                "responsible_parties, recommended_refund_brl, resolution_actions, and "
                "excluded_higher_priority_rules exactly. You MUST also preserve selected_entities "
                "and selected_evidence_ids exactly; never replace a populated ID list with an "
                "empty list. The policy agent may independently assess only confidence and "
                "confidence_basis. No Python confidence value is supplied: estimate confidence "
                "yourself from evidence completeness, consistency across sources, and certainty of "
                "the matched rule. Do not default to 1.0. For every agent, copy entity_candidates "
                "and evidence_candidates exactly from tool_result. For all other agents, preserve "
                "tool facts exactly. Your response, not the tool_result object, will be handed to "
                "the Coordinator. Do not add explanations. Copy agent_name, task_id, and "
                "source_digest exactly."
            ),
            user_prompt=json.dumps(
                {
                    "agent_name": self._agent_name.value,
                    "task_id": task.task_id,
                    "source_digest": source_digest,
                    "required_facts_schema": api_facts_model.model_json_schema(),
                    "source": source,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            response_model=response_model,
            schema_name=f"{self._agent_name.value}_generated_result",
            max_tokens=self._max_tokens,
        )
        if (
            generated.agent_name != self._agent_name
            or generated.task_id != task.task_id
            or generated.source_digest != source_digest
        ):
            raise RuntimeError(f"{self._agent_name.value} API result identity mismatch")

        api_facts = api_facts_model.model_validate(generated.facts).model_dump(
            mode="json", by_alias=True
        )
        validated_facts = result_facts_model.model_validate(api_facts).model_dump(mode="json")
        context_mismatches = self._context_mismatches(tool_result, generated)
        if context_mismatches:
            return self._mismatch_result(
                task,
                code="AGENT_API_CONTEXT_MISMATCH",
                mismatches=context_mismatches,
                message="agent API omitted or changed IDs supplied by the Python tool context",
            )
        policy_mismatches = self._policy_mismatches(tool_result.facts, validated_facts)
        if policy_mismatches:
            return self._mismatch_result(
                task,
                code="POLICY_API_MISMATCH",
                mismatches=policy_mismatches,
                message="policy API changed fields locked by the Python EC_POLICY_V1 evaluation",
            )
        api_warning = {
            "type": "api_generation",
            "provider": QWEN_PROVIDER,
            "model": QWEN_MODEL,
            "source_digest": source_digest,
            **(
                {"confidence_source": "qwen_api_self_assessment"}
                if self._agent_name == AgentName.POLICY
                else {}
            ),
        }
        return AgentResult(
            contract_version=task.contract_version,
            run_id=task.run_id,
            correlation_id=task.correlation_id,
            task_id=task.task_id,
            attempt=task.attempt,
            case_id=task.case_id,
            order_id=task.order_id,
            policy_version=task.policy_version,
            agent_name=self._agent_name,
            status=tool_result.status,
            facts=validated_facts,
            entity_candidates=EntityCandidates.model_validate(
                generated.entity_candidates.model_dump(mode="json")
            ),
            evidence_candidates=generated.evidence_candidates,
            warnings=[
                *generated.warnings,
                *(
                    [
                        {
                            "type": "python_policy_evaluation",
                            "policy_version": task.policy_version,
                            "matched_rule_priority": validated_facts["matched_rule_priority"],
                        }
                    ]
                    if self._agent_name == AgentName.POLICY
                    else []
                ),
                api_warning,
            ],
            errors=[],
        )

    def _policy_mismatches(
        self, evaluated_facts: dict[str, Any], generated_facts: dict[str, Any]
    ) -> list[str]:
        if self._agent_name != AgentName.POLICY:
            return []
        normalized_evaluation = PolicyDecision.model_validate(evaluated_facts).model_dump(
            mode="json"
        )
        locked_fields = (
            "bundle_version",
            "bundle_digest",
            "matched_rule_priority",
            "primary_issue",
            "case_status",
            "ranked_causes",
            "responsible_parties",
            "recommended_refund_brl",
            "resolution_actions",
            "selected_entities",
            "selected_evidence_ids",
            "excluded_higher_priority_rules",
        )
        return [
            field
            for field in locked_fields
            if self._canonical(normalized_evaluation.get(field))
            != self._canonical(generated_facts.get(field))
        ]

    def _context_mismatches(
        self,
        tool_result: AgentResult,
        generated: ApiGeneratedResponse[Any],
    ) -> list[str]:
        if self._agent_name not in {
            AgentName.ORDER_SELLER,
            AgentName.PAYMENT,
            AgentName.DELIVERY,
        }:
            return []
        mismatches: list[str] = []
        if self._canonical(generated.entity_candidates.model_dump(mode="json")) != self._canonical(
            tool_result.entity_candidates.model_dump(mode="json")
        ):
            mismatches.append("entity_candidates")
        if generated.evidence_candidates != tool_result.evidence_candidates:
            mismatches.append("evidence_candidates")
        return mismatches

    def _mismatch_result(
        self,
        task: AgentTask,
        *,
        code: str,
        mismatches: list[str],
        message: str,
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
            agent_name=self._agent_name,
            status=AgentStatus.CONFLICT,
            errors=[
                AgentError(
                    code=code,
                    path=",".join(mismatches),
                    message=message,
                    source=self._agent_name.value,
                    retryable=True,
                    retry_target=self._agent_name,
                )
            ],
        )

    @staticmethod
    def _canonical(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @staticmethod
    def _digest(value: object) -> str:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
