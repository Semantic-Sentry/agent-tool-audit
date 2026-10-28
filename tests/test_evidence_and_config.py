import json
from pathlib import Path

import pytest

from ata.policy import PolicyConfig, ToolClass, ToolPolicy
from ata.config import AuditConfig
from ata.evidence import EvidenceVault
from ata.interceptor import Interceptor
from ata.evaluator import Evaluator, Outcome
from ata.canary import generate_canary


def _policy():
    return PolicyConfig(
        agent_name="fake-agent",
        untrusted_channels=["rag_document"],
        tools={
            "read_document": ToolPolicy(class_type=ToolClass.SAFE),
            "http_post": ToolPolicy(class_type=ToolClass.EGRESS),
        },
    )


def test_config_hash_is_deterministic_regardless_of_dict_order():
    policy_a = _policy()
    policy_b = _policy()  # тот же состав, но собран отдельно

    cfg_a = AuditConfig(
        agent_name="demo", model="openai/gpt-4o-2024-11-20", model_provider="openrouter",
        n_iterations=30, policy=policy_a, vector_ids=["v2", "v1"],
    )
    cfg_b = AuditConfig(
        agent_name="demo", model="openai/gpt-4o-2024-11-20", model_provider="openrouter",
        n_iterations=30, policy=policy_b, vector_ids=["v1", "v2"],  # другой порядок
    )

    assert cfg_a.config_hash() == cfg_b.config_hash()


def test_config_hash_changes_when_policy_changes():
    # ВАЖНО: два НЕЗАВИСИМЫХ объекта policy, а не общий с мутацией после
    # создания cfg_a. AuditConfig хранит ссылку на policy, не копию,
    # поэтому мутация policy "задним числом" меняет и уже созданный cfg_a.
    policy_a = _policy()
    cfg_a = AuditConfig(
        agent_name="demo", model="m", model_provider="openrouter",
        n_iterations=10, policy=policy_a, vector_ids=["v1"],
    )

    policy_b = _policy()
    policy_b.tools["http_post"].allowed_domains.append("example.com")
    cfg_b = AuditConfig(
        agent_name="demo", model="m", model_provider="openrouter",
        n_iterations=10, policy=policy_b, vector_ids=["v1"],
    )

    assert cfg_a.config_hash() != cfg_b.config_hash()


def test_full_evidence_cycle_with_real_core(tmp_path):
    """commit_config -> одна итерация через настоящий interceptor/evaluator -> seal -> verify."""
    policy = _policy()
    cfg = AuditConfig(
        agent_name="fake-agent", model="test-model", model_provider="openrouter",
        n_iterations=1, policy=policy, vector_ids=["demo-vector"],
    )

    vault = EvidenceVault(run_id="test-run-1", out_dir=str(tmp_path / "run"))
    vault.commit_config(cfg.config_hash(), cfg.to_canonical_dict())

    canary = generate_canary("test-run-1", "demo-vector", 1)
    interceptor = Interceptor(policy, current_canary=canary)

    def raw_http_post(url, body):
        return "ok"  # без реального sink — events всё равно содержат policy_decision

    http_post = interceptor.wrap_tool("http_post", raw_http_post)
    http_post(url="http://example.com", body=f"leak {canary}")

    result = Evaluator.evaluate(
        events=interceptor.events, sink_captures=[],
        agent_text_output="", canary=canary,
    )
    assert result.outcome == Outcome.UNBLOCKED  # нет sink -> не CONFIRMED

    vault.append_iteration(
        vector_id="demo-vector", iteration=1, canary=canary,
        outcome=result.outcome.value, influence_detected=result.influence_detected,
        events=result.events, matched_capture_id=result.matched_capture_id,
    )
    seal_result = vault.seal()
    assert "manifest_hash" in seal_result

    verify_result = EvidenceVault.verify(str(tmp_path / "run"))
    assert verify_result["valid"] is True
    assert verify_result["total_records"] == 3  # commit_config + iteration + seal


def test_verify_detects_tampering(tmp_path):
    out_dir = tmp_path / "run2"
    vault = EvidenceVault(run_id="tamper-test", out_dir=str(out_dir))
    vault.commit_config("fakehash", {"x": 1})
    vault.seal()

    # подменяем тело одной записи, не трогая остальные поля
    chain_path = out_dir / "chain.jsonl"
    lines = chain_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["payload"]["config_hash"] = "tampered-value"
    lines[0] = json.dumps(first, sort_keys=True, ensure_ascii=False)
    chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = EvidenceVault.verify(str(out_dir))
    assert result["valid"] is False
    assert "hash mismatch" in result["reason"]


def test_cannot_append_after_seal(tmp_path):
    vault = EvidenceVault(run_id="seal-test", out_dir=str(tmp_path / "run3"))
    vault.commit_config("h", {})
    vault.seal()
    with pytest.raises(RuntimeError):
        vault.commit_config("h2", {})
