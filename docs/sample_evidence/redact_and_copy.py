#!/usr/bin/env python3
"""
Копирует chain.jsonl/manifest.json из runs/<run_id>/ в публичную sample_evidence
директорию, заменяя реальные канарейки на [REDACTED:CANARY] во ВСЕХ строковых
полях (включая top-level "canary" в iteration_result, которое append_iteration
пишет без редактирования -- в отличие от событий, где interceptor.py уже
редактирует args_norm).

ВАЖНО: это ломает verify()! Редактирование меняет тело записей, значит
пересчитанный hash каждой записи больше не совпадёт с оригинальным "hash"
полем, и prev_hash следующей записи тоже разойдётся. Поэтому этот скрипт
НЕ просто патчит строки -- он пересобирает цепочку заново поверх
отредактированных payload'ов, пересчитывая hash и prev_hash корректно,
и затем пересчитывает manifest/manifest_hash. Итоговый manifest_hash
в sample_evidence НЕ совпадает с оригинальным manifest_hash из notes --
это ОЖИДАЕМО и должно быть явно помечено в README рядом, иначе это
выглядит как расхождение/фальсификация, а не как следствие редактирования.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

CANARY_RE = re.compile(r"CANARY-[A-Za-z0-9\-]+")


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _redact_strings(obj):
    if isinstance(obj, str):
        return CANARY_RE.sub("[REDACTED:CANARY]", obj)
    if isinstance(obj, dict):
        return {k: _redact_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_strings(v) for v in obj]
    return obj


def redact_and_rechain(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    src_chain = src_dir / "chain.jsonl"
    lines = [json.loads(l) for l in src_chain.read_text(encoding="utf-8").splitlines() if l.strip()]

    prev_hash = "0" * 64
    out_lines = []
    for rec in lines:
        body = {k: v for k, v in rec.items() if k != "hash"}
        body["payload"] = _redact_strings(body["payload"])
        body["prev_hash"] = prev_hash
        body_json = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        new_hash = _sha256(body_json)
        out_rec = dict(body)
        out_rec["hash"] = new_hash
        out_lines.append(out_rec)
        prev_hash = new_hash

    (dst_dir / "chain.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in out_lines) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "run_id": lines[0]["run_id"],
        "total_events": len(out_lines),
        "final_chain_hash": prev_hash,
        "chain_file": "chain.jsonl",
        "sealed_at": lines[-1]["ts"],
        "note": "REDACTED COPY -- hashes recomputed after canary redaction, will NOT match original run's manifest_hash. See README.md in this directory.",
    }
    manifest_json = json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2)
    (dst_dir / "manifest.json").write_text(manifest_json, encoding="utf-8")

    manifest_hash = _sha256(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    )
    print(f"{dst_dir}: redacted chain written, {len(out_lines)} records")
    print(f"  recomputed final_chain_hash: {prev_hash}")
    print(f"  recomputed manifest_hash:    {manifest_hash}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: redact_and_copy.py <src_run_dir> <dst_dir>")
        sys.exit(1)
    redact_and_rechain(Path(sys.argv[1]), Path(sys.argv[2]))
