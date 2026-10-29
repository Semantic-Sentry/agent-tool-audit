# Sample evidence: cross-model risk divergence (echo vector, N=20)

These are redacted, re-chained copies of two real audit runs referenced in
`docs/sample_report.md`. They exist so a skeptical reader can independently
verify the hash-chain integrity claim without trusting our word for it.

## What these are

- `luna/` — `openai/gpt-6-luna`, vector `customer_message-echo_diagnostic_code`, N=20
- `deepseek/` — `deepseek/deepseek-v4.1-flash-1017`, same vector, same N

Each directory is a redacted copy of `runs/<run_id>/chain.jsonl` +
`manifest.json` from the original audit. Every canary value
(`CANARY-<run_id>-<vector_id>-<iteration>-<uuid>`) has been replaced with
`[REDACTED:CANARY]` in all event payloads before publishing.

## Important: hashes here do NOT match the original run

Because redaction changes record content, every record's hash and the
final chain/manifest hash had to be **recomputed from the redacted data**.
These are NOT the same hashes referenced as the external anchors
(`config_hash` sent before the run, `manifest_hash` sent after) in the
original client-facing audit record for this run. That is expected and
correct — the original hashes anchor the *real, unredacted* run; these
hashes anchor *this redacted sample*, so you can verify that the sample
itself hasn't been tampered with after publishing, even though it is not
the primary evidentiary artifact for the underlying audit.

Recomputed hashes (verifiable with the command below):

| Run | final_chain_hash | manifest_hash |
|---|---|---|
| luna (N=20) | `0cc3019675d0fdb1cbf65658aee2811c764f28ae39b012d2f492ad6ea99ee4b5` | `23f5013629e0f7783b0bcfc1cfdb41fd73ba26c5ed3f3070896e0bd48369a936` |
| deepseek (N=20) | `90284a7b73b3f564bfc6b03b1b2b5f47d240e89870c130cd2b19edc963a717a0` | `1cb29604b795c7b9471de75ba74f39456ddd52820d5927c7af64734da24ecffa` |

## Verify it yourself

```bash
python3 -c "
from ata.evidence import EvidenceVault
print(EvidenceVault.verify('docs/sample_evidence/echo_divergence_n20/luna'))
print(EvidenceVault.verify('docs/sample_evidence/echo_divergence_n20/deepseek'))
"
```

Expected output: `{'valid': True, 'total_records': 22, ...}` for both. A
`False` result, or a hash mismatch error, means either this copy was
tampered with after publishing, or the redaction/re-chaining process has
a bug — in either case, treat the sample as unverified and flag it.

## What's NOT proven by this verification

Integrity verification confirms the *recorded* events were not altered
after this redacted copy was created. It does not independently confirm
that every tool call the live agent made was captured (observation
completeness is a separate, unverified claim — see `docs/methodology.md`),
and it does not confirm anything about production behavior outside this
sandboxed test environment.
