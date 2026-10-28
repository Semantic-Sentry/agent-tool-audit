import hashlib
import json
import time
from dataclasses import dataclass, asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _to_jsonable(obj: Any) -> Any:
    """Рекурсивно превращает dataclass'ы (ToolCallEvent, IterationResult, Enum) в JSON-совместимые структуры."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if hasattr(obj, "value") and hasattr(obj, "name"):  # Enum (Outcome, ToolClass)
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


class EvidenceVault:
    """
    Append-only hash-chain лог для одного прогона (run_id).
    seq=0 — commit_config (внешний якорь №1).
    Каждое последующее событие ссылается на hash предыдущего.
    seal() — финальный манифест (внешний якорь №2).
    """

    def __init__(self, run_id: str, out_dir: str):
        self.run_id = run_id
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.chain_path = self.out_dir / "chain.jsonl"
        self.manifest_path = self.out_dir / "manifest.json"
        self._seq = 0
        self._prev_hash = "0" * 64  # genesis
        self._sealed = False

    def _append(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self._sealed:
            raise RuntimeError("EvidenceVault is sealed; cannot append further events")

        record_body = {
            "seq": self._seq,
            "run_id": self.run_id,
            "event": event_type,
            "prev_hash": self._prev_hash,
            "ts": time.time(),
            "payload": _to_jsonable(payload),
        }
        body_json = json.dumps(record_body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        record_hash = _sha256(body_json)
        record = dict(record_body)
        record["hash"] = record_hash

        with open(self.chain_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")

        self._prev_hash = record_hash
        self._seq += 1
        return record

    def commit_config(self, config_hash: str, config_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        Первая запись в цепочке. config_hash должен быть опубликован/отправлен
        клиенту ДО начала прогона (внешний якорь №1) — эта функция сама
        якорь не создаёт, только фиксирует его в цепочке.
        """
        return self._append("commit_config", {
            "config_hash": config_hash,
            "config_snapshot": config_snapshot,
        })

    def append_iteration(
        self,
        vector_id: str,
        iteration: int,
        canary: str,
        outcome: str,
        influence_detected: bool,
        events: List[Any],              # List[ToolCallEvent]
        matched_capture_id: Optional[str],
    ) -> Dict[str, Any]:
        return self._append("iteration_result", {
            "vector_id": vector_id,
            "iteration": iteration,
            "canary": canary,
            "outcome": outcome,
            "influence_detected": influence_detected,
            "events": [_to_jsonable(e) for e in events],
            "matched_capture_id": matched_capture_id,
        })

    def append_error(self, vector_id: str, iteration: int, error_msg: str) -> Dict[str, Any]:
        return self._append("run_error", {
            "vector_id": vector_id,
            "iteration": iteration,
            "error_msg": error_msg,
        })

    def seal(self) -> Dict[str, Any]:
        """
        Финальная запись + манифест. Хэш манифеста — внешний якорь №2,
        публикуется/отправляется клиенту ПОСЛЕ прогона.
        """
        if self._sealed:
            raise RuntimeError("already sealed")

        seal_record = self._append("seal", {"total_events": self._seq})

        manifest = {
            "run_id": self.run_id,
            "total_events": self._seq,
            "final_chain_hash": seal_record["hash"],
            "chain_file": str(self.chain_path.name),
            "sealed_at": time.time(),
        }
        manifest_json = json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2)
        self.manifest_path.write_text(manifest_json, encoding="utf-8")

        manifest_hash = _sha256(
            json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        )
        self._sealed = True
        return {"manifest": manifest, "manifest_hash": manifest_hash}

    @staticmethod
    def verify(out_dir: str) -> Dict[str, Any]:
        """
        Независимая проверка целостности: пересчитывает цепочку с нуля
        и сверяет с hash каждой записи. Не требует объекта EvidenceVault.
        """
        chain_path = Path(out_dir) / "chain.jsonl"
        if not chain_path.exists():
            return {"valid": False, "reason": "chain.jsonl not found"}

        prev_hash = "0" * 64
        expected_seq = 0

        with open(chain_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)

                if record["seq"] != expected_seq:
                    return {"valid": False, "reason": f"seq mismatch at line {line_no}: expected {expected_seq}, got {record['seq']}"}
                if record["prev_hash"] != prev_hash:
                    return {"valid": False, "reason": f"prev_hash mismatch at line {line_no} (seq={record['seq']})"}

                claimed_hash = record["hash"]
                record_body = {k: v for k, v in record.items() if k != "hash"}
                body_json = json.dumps(record_body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                recomputed_hash = _sha256(body_json)

                if recomputed_hash != claimed_hash:
                    return {"valid": False, "reason": f"hash mismatch at line {line_no} (seq={record['seq']})"}

                prev_hash = claimed_hash
                expected_seq += 1

        return {"valid": True, "total_records": expected_seq, "final_hash": prev_hash}
