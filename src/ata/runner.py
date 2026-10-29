import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

from ata.canary import generate_canary, seed_payload
from ata.config import AuditConfig
from ata.evaluator import Evaluator, IterationResult
from ata.evidence import EvidenceVault
from ata.interceptor import Interceptor
from ata.scenarios import SCENARIOS, Scenario
from ata.sink import LocalSink
from ata.stats import aggregate_outcomes
from ata.vectors import Vector, load_vectors
from mocks.tools import TOOL_SCHEMAS

load_dotenv()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"
MAX_TURNS = 5


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set (check .env)")
    return key


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, p: int, c: int) -> None:
        self.prompt_tokens += p
        self.completion_tokens += c

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


_pricing_cache: Dict[str, Tuple[float, float]] = {}


def fetch_model_pricing(model: str) -> Optional[Tuple[float, float]]:
    if model in _pricing_cache:
        return _pricing_cache[model]
    try:
        req = urllib.request.Request(MODELS_URL, headers={"Authorization": f"Bearer {_api_key()}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        for m in data.get("data", []):
            if m.get("id") == model:
                pricing = m.get("pricing", {})
                p = float(pricing.get("prompt", 0))
                c = float(pricing.get("completion", 0))
                _pricing_cache[model] = (p, c)
                return (p, c)
    except Exception as e:
        print(f"  [warn] pricing fetch failed for {model}: {e}")
    return None


def estimate_cost(usage: Usage, model: str) -> Optional[float]:
    pricing = fetch_model_pricing(model)
    if pricing is None:
        return None
    p_price, c_price = pricing
    return usage.prompt_tokens * p_price + usage.completion_tokens * c_price


def call_openrouter(messages: List[dict], model: str, tools: Optional[list] = None) -> dict:
    body = json.dumps({
        "model": model, "messages": messages,
        "tools": tools if tools is not None else TOOL_SCHEMAS, "temperature": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        OPENROUTER_URL, data=body,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _load_all_vectors() -> Dict[str, Vector]:
    all_vectors: Dict[str, Vector] = {}
    for f in sorted(Path("vectors").glob("*.json")):
        for v in load_vectors(str(f)):
            if v.id in all_vectors:
                raise ValueError(f"duplicate vector id across files: {v.id}")
            all_vectors[v.id] = v
    return all_vectors


def run_scenario_iteration(
    model: str, scenario: Scenario, vector: Vector,
    run_id: str, iteration: int, sink: LocalSink,
) -> Tuple[IterationResult, Usage, str]:
    canary = generate_canary(run_id, vector.id, iteration)
    seeded = seed_payload(vector.payload, canary)

    tools_impl = scenario.build_tools(seeded, canary, sink)
    interceptor = Interceptor(scenario.policy, current_canary=canary)
    wrapped = {name: interceptor.wrap_tool(name, fn) for name, fn in tools_impl.items()}

    messages = scenario.build_messages(seeded)
    usage = Usage()
    final_text = ""

    for _ in range(MAX_TURNS):
        resp = call_openrouter(messages, model, tools=scenario.tool_schemas)
        if "error" in resp:
            raise RuntimeError(f"OpenRouter error: {resp['error']}")

        u = resp.get("usage", {})
        usage.add(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))

        msg = resp["choices"][0]["message"]
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            final_text = msg.get("content", "") or ""
            break

        messages.append(msg)
        for tc in tool_calls:
            name = tc["function"]["name"]
            raw_args = tc["function"]["arguments"]
            try:
                args = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                args = {}

            fn = wrapped.get(name)
            if fn is None:
                out = f"unknown tool: {name}"
            else:
                try:
                    out = fn(**args)
                except Exception as e:
                    out = f"error: {e}"

            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": str(out)})

    captures = sink.find_canary_captures(canary)
    result = Evaluator.evaluate(
        events=interceptor.events, sink_captures=captures,
        agent_text_output=final_text, canary=canary,
    )
    return result, usage, canary


def run_pilot(models: List[str], vector_id: str, n: int) -> None:
    """Дешёвая разведка без evidence-цикла: быстро проверить, вообще ли вектор что-то даёт."""
    all_vectors = _load_all_vectors()
    if vector_id not in all_vectors:
        raise ValueError(f"unknown vector_id {vector_id}; available: {sorted(all_vectors)}")
    vector = all_vectors[vector_id]
    scenario = SCENARIOS[vector.scenario]

    sink = LocalSink(port=8899)
    sink.start()
    run_id = f"pilot-{int(time.time())}"
    summary = []

    try:
        for model in models:
            print(f"\n=== model: {model} | vector: {vector_id} | scenario: {scenario.name} ===")
            sink.clear()
            outcomes, errors = [], 0
            total_usage = Usage()

            for i in range(1, n + 1):
                try:
                    result, usage, canary = run_scenario_iteration(model, scenario, vector, run_id, i, sink)
                    total_usage.add(usage.prompt_tokens, usage.completion_tokens)
                    outcomes.append(result.outcome.value)
                    cost = estimate_cost(usage, model)
                    cost_str = f"${cost:.5f}" if cost is not None else "n/a"
                    print(f"  iter {i}: {result.outcome.value:10s} tokens={usage.total_tokens:4d} cost={cost_str}")
                except Exception as e:
                    errors += 1
                    print(f"  iter {i}: ERROR - {e}")

            total_cost = estimate_cost(total_usage, model)
            avg_cost = (total_cost / n) if total_cost is not None else None
            summary.append({
                "model": model, "vector_id": vector_id, "n": n, "errors": errors,
                "outcomes": outcomes, "total_tokens": total_usage.total_tokens,
                "total_cost_usd": total_cost, "avg_cost_per_iteration_usd": avg_cost,
            })
    finally:
        sink.stop()

    print("\n=== PILOT SUMMARY ===")
    for s in summary:
        avg = s["avg_cost_per_iteration_usd"]
        avg_str = f"${avg:.5f}" if avg is not None else "n/a"
        print(f"{s['model']:40s} outcomes={s['outcomes']} avg_cost/iter={avg_str} errors={s['errors']}")

    out_path = Path("runs") / f"{run_id}-pilot-summary.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSaved: {out_path}")


def run_audit(model: str, vector_ids: List[str], n: int, out_dir: str) -> dict:
    """Полноценный прогон с evidence-цепочкой: commit_config -> итерации -> seal -> stats."""
    all_vectors = _load_all_vectors()
    vectors = [all_vectors[vid] for vid in vector_ids]

    # Защита от случайного прогона непроверенных TODO-гипотез на деньги клиента/свои.
    for vid in vector_ids:
        if vid.upper().startswith("HYP-"):
            raise ValueError(
                f"{vid} looks like a pending hypothesis vector (id starts with HYP-), "
                f"not yet validated with a manual N=1-3 check. Run it manually first, "
                f"then remove the HYP- prefix / PENDING_EVALUATION status before using run_audit."
            )

    scenario_names = {v.scenario for v in vectors}
    if len(scenario_names) != 1:
        raise ValueError(f"run_audit requires all vectors to share one scenario, got: {scenario_names}")
    scenario = SCENARIOS[next(iter(scenario_names))]

    cfg = AuditConfig(
        agent_name=scenario.policy.agent_name, model=model, model_provider="openrouter",
        n_iterations=n, policy=scenario.policy, vector_ids=vector_ids,
        framework="none", framework_version="unknown",
    )

    run_id = f"audit-{int(time.time())}"
    vault = EvidenceVault(run_id=run_id, out_dir=out_dir)
    vault.commit_config(cfg.config_hash(), cfg.to_canonical_dict())
    print(f"run_id: {run_id}")
    print(f"config_hash (send to client BEFORE run): {cfg.config_hash()}")

    sink = LocalSink(port=8900)
    sink.start()
    outcomes_by_vector: Dict[str, List[str]] = {v.id: [] for v in vectors}

    try:
        for vector in vectors:
            sink.clear()
            print(f"\n=== vector: {vector.id} ===")
            for i in range(1, n + 1):
                try:
                    result, usage, canary = run_scenario_iteration(model, scenario, vector, run_id, i, sink)
                    vault.append_iteration(
                        vector_id=vector.id, iteration=i, canary=canary,
                        outcome=result.outcome.value, influence_detected=result.influence_detected,
                        events=result.events, matched_capture_id=result.matched_capture_id,
                    )
                    outcomes_by_vector[vector.id].append(result.outcome.value)
                    print(f"  iter {i}: {result.outcome.value}")
                except Exception as e:
                    vault.append_error(vector.id, i, str(e))
                    outcomes_by_vector[vector.id].append("ERROR")
                    print(f"  iter {i}: ERROR - {e}")
    finally:
        sink.stop()

    seal_result = vault.seal()
    print(f"\nmanifest_hash (send to client AFTER run): {seal_result['manifest_hash']}")

    print("\n=== STATS ===")
    counts = aggregate_outcomes(outcomes_by_vector)
    for c in counts:
        print(f"{c.vector_id}:")
        print(f"  attempt-or-worse:   {c.attempt_or_worse_interval()}")
        print(f"  unblocked-or-worse: {c.unblocked_or_worse_interval()}")
        print(f"  confirmed:          {c.confirmed_interval()}")

    return {
        "run_id": run_id, "out_dir": out_dir,
        "config_hash": cfg.config_hash(), "manifest_hash": seal_result["manifest_hash"],
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)

    p_pilot = sub.add_parser("pilot", help="quick exploration, no evidence chain")
    p_pilot.add_argument("--models", nargs="+", default=[
        "openai/gpt-6-luna", "deepseek/deepseek-v4.1-flash-1017",
    ])
    p_pilot.add_argument("--vector-id", required=True)
    p_pilot.add_argument("--n", type=int, default=5)

    p_audit = sub.add_parser("audit", help="full run with hash-chain evidence + stats")
    p_audit.add_argument("--model", required=True)
    p_audit.add_argument("--vector-ids", nargs="+", required=True)
    p_audit.add_argument("--n", type=int, default=5)
    p_audit.add_argument("--out-dir", default=None)

    args = parser.parse_args()
    if args.mode == "pilot":
        run_pilot(args.models, args.vector_id, args.n)
    else:
        out_dir = args.out_dir or f"runs/audit-{int(time.time())}"
        run_audit(args.model, args.vector_ids, args.n, out_dir)
