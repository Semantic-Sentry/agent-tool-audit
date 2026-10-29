# agent-tool-audit

Security audit of AI agents with tool access — measured at the
**tool-execution level**, not the text-response level.

Most prompt-injection testing checks whether a model's *reply* sounds
compliant. This measures whether an untrusted input actually causes an
agent to **call a tool** with attacker-influenced arguments, and whether
that data **physically reaches** an independent receiver — not whether
the tool claims it succeeded.

**→ [Read the sample report](docs/sample_report.md)** — real,
independently verifiable results, including an 11x risk difference
between two models on the identical agent and vector:

| Model | Vector | Result (N=20) |
|---|---|---|
| `openai/gpt-6-luna` | customer-message echo | 1/20 (5.0%) |
| `deepseek/deepseek-v4.1-flash-1017` | customer-message echo | 11/20 (55.0%) |

Non-overlapping 95% confidence intervals. Same agent, same prompt, same
vector — only the model changed.

## What this is

- A security audit harness for AI agents with tool access (think: a
  support agent that reads tickets/documents and can call tools that
  send email, write to a CRM, hit a webhook, etc.)
- Tests whether indirect prompt injection — hostile instructions hidden
  in content the agent reads, not typed by the user — causes the agent
  to call a tool it shouldn't, with data it shouldn't be sending.
- Every finding is graded `NONE → ATTEMPT → UNBLOCKED → CONFIRMED`,
  where `CONFIRMED` means a canary value was physically captured by a
  receiver the auditor controls — not inferred from the model's own
  claim that it "sent" something.
- Every run is anchored by a hash-chain: a config hash sent to the
  client *before* the run, a manifest hash sent *after* — so the
  methodology is fixed before results exist and the result set can't be
  silently edited afterward.

## What this is not

- Not a general-purpose LLM red-teaming or jailbreak scanner. It
  deliberately does not compete with text-response-level tools
  (Promptfoo, garak, etc.) on breadth of attack prompts.
- Not a production vulnerability scanner — all results are sandboxed;
  see *Scope & Boundaries* in the sample report for exactly what is and
  isn't covered.
- Not a SaaS product. This is the harness behind a hands-on, scoped
  security audit service.

## Documentation

- [`docs/sample_report.md`](docs/sample_report.md) — start here: the
  findings, in the form a client would actually read.
- [`docs/methodology.md`](docs/methodology.md) — outcome definitions,
  statistical approach (Wilson intervals, why small-N results are
  reported differently), and explicit limitations.
- [`docs/sample_evidence/`](docs/sample_evidence/) — redacted, re-chained
  copies of the two N=20 runs referenced in the sample report, with a
  one-command script to independently verify hash-chain integrity.

## Verify the sample evidence yourself

```bash
pip install -e ".[dev]"
python3 -c "
from ata.evidence import EvidenceVault
print(EvidenceVault.verify('docs/sample_evidence/echo_divergence_n20/luna'))
print(EvidenceVault.verify('docs/sample_evidence/echo_divergence_n20/deepseek'))
"
```

Expected: `{'valid': True, 'total_records': 22, ...}` for both runs.

## Status

Validation phase. The harness, evidence chain, and statistics have been
tested end-to-end against two models via OpenRouter. No framework-specific
adapter (LangChain/CrewAI/etc.) has been built yet — see *Known gaps* in
the methodology doc. This is a scoped, hands-on audit service, not a
hosted product.
