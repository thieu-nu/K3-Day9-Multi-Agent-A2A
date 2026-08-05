from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from agents.api_runner import ApiGeneratedAgent
from agents.coordinator import (
    AgentName,
    AgentRunner,
    AtomicJsonOutputStore,
    CoordinatorAgent,
    CoordinatorConfig,
    JsonlTraceSink,
)
from agents.delivery_agent import DeliveryAgent
from agents.order_seller_agent import OrderSellerAgent
from agents.payment_agent import PaymentAgent
from agents.policy_agent import PolicyAgent
from agents.verifier_agent import VerifierAgent
from utils.data_loader import OlistDataLoader
from utils.llm_client import (
    QWEN_MODEL,
    QWEN_PARAMETER_SIZE_B,
    QWEN_PROVIDER,
    TogetherStructuredClient,
)

CASE_FILE_PATTERN = re.compile(r"EC_[0-9]{3}\.json")


async def run_batch(
    root: Path,
    *,
    expected_count: int = 50,
    use_api: bool = False,
    case_id: str | None = None,
) -> int:
    input_directory = root / "input"
    output_directory = root / "output"
    logging_directory = root / "logging"
    case_paths = sorted(
        path
        for path in input_directory.iterdir()
        if path.is_file() and CASE_FILE_PATTERN.fullmatch(path.name)
    )
    if case_id is not None:
        if not re.fullmatch(r"EC_[0-9]{3}", case_id):
            raise ValueError("--case must match EC_NNN")
        selected_path = input_directory / f"{case_id}.json"
        if selected_path not in case_paths:
            raise FileNotFoundError(f"case input does not exist: {selected_path}")
        case_paths = [selected_path]
    elif len(case_paths) != expected_count:
        raise RuntimeError(f"expected {expected_count} case files, found {len(case_paths)}")

    output_directory.mkdir(parents=True, exist_ok=True)
    logging_directory.mkdir(parents=True, exist_ok=True)
    trace_path = logging_directory / "trace.jsonl"
    trace_path.write_text("", encoding="utf-8")

    data = OlistDataLoader(root / "data")
    runners: dict[AgentName, AgentRunner] = {
        AgentName.ORDER_SELLER: OrderSellerAgent(data),
        AgentName.PAYMENT: PaymentAgent(data),
        AgentName.DELIVERY: DeliveryAgent(data),
        AgentName.POLICY: PolicyAgent(),
        AgentName.VERIFIER: VerifierAgent(data),
    }
    if use_api:
        load_dotenv(root / ".env")
        client = TogetherStructuredClient(timeout_seconds=120.0)
        runners = {
            name: ApiGeneratedAgent(agent_name=name, tool_runner=runner, client=client)
            for name, runner in runners.items()
        }

    coordinator = CoordinatorAgent(
        order_seller_agent=runners[AgentName.ORDER_SELLER],
        payment_agent=runners[AgentName.PAYMENT],
        delivery_agent=runners[AgentName.DELIVERY],
        policy_agent=runners[AgentName.POLICY],
        verifier_agent=runners[AgentName.VERIFIER],
        output_store=AtomicJsonOutputStore(output_directory),
        trace_sink=JsonlTraceSink(trace_path),
        config=CoordinatorConfig(
            agent_timeout_seconds=150.0 if use_api else 60.0,
            max_verification_rounds=3 if use_api else 2,
        ),
    )
    run_id = f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    failures: list[dict[str, object]] = []
    passed_case_ids: list[str] = []
    for path in case_paths:
        raw_case = json.loads(path.read_text(encoding="utf-8"))
        result = await coordinator.coordinate(
            source_filename=path.name,
            case_input=raw_case,
            run_id=run_id,
        )
        if not result.success:
            failures.append(
                {
                    "case_id": result.case_id,
                    "errors": [error.model_dump(mode="json") for error in result.errors],
                }
            )
        elif result.case_id is not None:
            passed_case_ids.append(result.case_id)

    if failures:
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "passed_case_ids": passed_case_ids,
                    "successful_outputs_preserved": len(passed_case_ids),
                    "failures": failures,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    output_paths = [output_directory / path.name for path in case_paths]
    output_paths = [path for path in output_paths if path.is_file()]
    required_output_count = len(case_paths)
    if len(output_paths) != required_output_count:
        raise RuntimeError(
            "run completed but selected output count is "
            f"{len(output_paths)}, expected {required_output_count}"
        )
    metadata = {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "policy_version": "EC_POLICY_V1",
        "framework": f"langgraph {version('langgraph')}",
        "runtime": f"Python {sys.version.split()[0]}",
        "libraries": {
            "polars": version("polars"),
            "pydantic": version("pydantic"),
            "together": version("together"),
        },
        "agent_execution": {
            "mode": "qwen_api_generated" if use_api else "deterministic",
            "order_seller": "qwen_api_generated_from_csv" if use_api else "deterministic_csv",
            "payment": "qwen_api_generated_from_csv" if use_api else "deterministic_csv",
            "delivery": "qwen_api_generated_from_csv" if use_api else "deterministic_csv",
            "policy": "qwen_api_generated_decision" if use_api else "deterministic_rule_engine",
            "verifier": (
                "qwen_api_generated_verification" if use_api else "deterministic_independent_check"
            ),
        },
        "models": [
            {
                "agent": agent,
                "model": QWEN_MODEL if use_api else "deterministic/no-llm",
                "parameter_size": f"{QWEN_PARAMETER_SIZE_B:g}B" if use_api else "0B",
            }
            for agent in ("order_seller", "payment", "delivery", "policy", "verifier")
        ],
        "api_model": {
            "provider": QWEN_PROVIDER,
            "model": QWEN_MODEL,
            "parameter_size_b": QWEN_PARAMETER_SIZE_B,
            "usage": (
                "structured agent result generation for every successful tool handoff"
                if use_api
                else "optional structured language tasks; not used for arithmetic or policy"
            ),
        },
        "input_count": len(case_paths),
        "passed_count": len(output_paths),
        "output_count": len(output_paths),
        "source_revision": source_revision(root),
        "case_filter": case_id,
    }
    (logging_directory / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


def source_revision(root: Path) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={root.as_posix()}",
            "rev-parse",
            "HEAD",
        ],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    revision = completed.stdout.strip()
    return revision if completed.returncode == 0 and revision else "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Olist multi-agent dispute batch")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="repository root",
    )
    parser.add_argument("--expected-count", type=int, default=50)
    parser.add_argument(
        "--case",
        type=str,
        help="run exactly one case such as EC_002; preserve outputs for other cases",
    )
    parser.add_argument(
        "--use-api",
        action="store_true",
        help="use Qwen API to generate every successful agent result from tool context",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(
        run_batch(
            args.root.resolve(),
            expected_count=args.expected_count,
            use_api=args.use_api,
            case_id=args.case,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
