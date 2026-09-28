"""The coordination brain: a manual agentic loop over the Nolambur tools.

Claude plays four internal roles in sequence - Detector, Investigator,
Coordinator, Monitor - deciding the tool order itself rather than following
hard-coded control flow. After the loop, one more call turns the transcript into
a structured CASE DECISION.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import anthropic

from .config import ORCHESTRATOR_MODEL, SCORE_ACT, SCORE_INVESTIGATE
from .tools import TOOL_SCHEMAS, run_tool

SYSTEM_PROMPT = f"""You are the coordination brain of "Operation Nolambur", a real-time system that
intercepts UPI mule chains from digital-arrest scams. A victim transaction has just been
flagged. Work it through four internal roles, in order, choosing tools yourself:

1. DETECTOR - score the flagged transfer with `score_transaction`. Note the probability,
   whether it was scored against the real background graph, and the layer/corridor.
2. INVESTIGATOR - if the score is >= {SCORE_INVESTIGATE} OR the transfer fits the
   digital-arrest pattern (~5L bursts; victim in Tamil Nadu; receiver in Uttarakhand /
   Rajasthan / Delhi / Haryana), then: `get_account_profile` on the receiver,
   `check_suspect_registry`, and `list_downstream_transfers` to find the next hop. Feed
   those hops into `score_transfer_chain`.
3. COORDINATOR - decide freeze / watch / clear. Call `freeze_account` + `file_1930_report`
   only when a high score (>= {SCORE_ACT}) is corroborated by at least one INDEPENDENT
   signal: a registry hit, a mule-shaped profile (fast turnaround, many inbound
   counterparties, near-5L transfers), or confirmed onward layering. A high score alone,
   or one weak signal alone, is "watch" - not "freeze". Whenever you freeze, file, or
   decide to watch, `notify_officer` with a one-line summary (accounts, amount, corridor,
   action); priority "critical" for an active in-progress chain, "high" otherwise.
4. MONITOR - if you froze or are watching, call `watch_downstream_stream` (optionally
   filtered to the corridor) to pick up live activity, and `notify_officer` again if it
   surfaces new hits on the same corridor.

Ground rules:
- The T-GNN checkpoint is finetune-only, val F1 ~0.07. A high score means "structurally
  mule-like", not a calibrated probability. Never act on it alone.
- `check_suspect_registry`, `freeze_account` and `file_1930_report` send real HTTP
  requests, but by default to the bridge's SANDBOX registry, gateway and 1930 portal - no
  bank, NPCI or government system. The mock registry's answer comes from the dataset label. Each result says whether it was sandboxed; say so in your writeup. The scoring and *_transfers tools are real.
- Be terse: one or two sentences per decision. Finish with a short section headed
  "CASE DECISION".
"""

CASE_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["freeze", "watch", "clear"]},
        "fraud_score": {"type": "number"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "flagged_accounts": {"type": "array", "items": {"type": "string"}},
        "corroborating_signals": {"type": "array", "items": {"type": "string"}},
        "actions_taken": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
        "model_caveat": {"type": "string"},
    },
    "required": [
        "verdict",
        "fraud_score",
        "confidence",
        "flagged_accounts",
        "corroborating_signals",
        "actions_taken",
        "rationale",
        "model_caveat",
    ],
    "additionalProperties": False,
}

EventHook = Callable[[str, dict[str, Any]], None]


def _text(response: anthropic.types.Message) -> str:
    return "\n".join(block.text for block in response.content if block.type == "text").strip()


def _emit(hook: EventHook | None, kind: str, data: dict[str, Any]) -> None:
    if hook is not None:
        hook(kind, data)


def run(
    transaction: dict[str, Any],
    *,
    model: str | None = None,
    max_iterations: int = 12,
    on_event: EventHook | None = None,
) -> dict[str, Any]:
    model = model or ORCHESTRATOR_MODEL
    client = anthropic.Anthropic()

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                "A UPI transaction has been flagged for review:\n"
                f"{json.dumps(transaction, indent=2)}\n\nWork the case."
            ),
        }
    ]

    narrative = ""
    for _ in range(max_iterations):
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        step_text = _text(response)
        if step_text:
            _emit(on_event, "assistant", {"text": step_text})

        if response.stop_reason == "refusal":
            detail = getattr(response, "stop_details", None)
            raise RuntimeError(f"model refused: {detail}")

        if response.stop_reason in ("end_turn", "max_tokens", "stop_sequence"):
            narrative = step_text
            break

        if response.stop_reason == "pause_turn":
            continue

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            _emit(on_event, "tool_call", {"name": block.name, "input": dict(block.input)})
            content, is_error = run_tool(block.name, dict(block.input))
            _emit(on_event, "tool_result", {"name": block.name, "content": content, "is_error": is_error})
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                }
            )

        if not tool_results:
            narrative = step_text
            break

        messages.append({"role": "user", "content": tool_results})
    else:
        narrative = narrative or "(stopped: max_iterations reached without a final answer)"

    decision = _structured_decision(client, model, messages)
    return {"model": model, "narrative": narrative, "decision": decision, "messages": messages}


def _structured_decision(
    client: anthropic.Anthropic,
    model: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            tool_choice={"type": "none"},
            messages=messages
            + [{"role": "user", "content": "Output the final CASE DECISION as structured JSON."}],
            output_config={"format": {"type": "json_schema", "schema": CASE_DECISION_SCHEMA}},
        )
        text = next(block.text for block in response.content if block.type == "text")
        return json.loads(text)
    except Exception as error:  # noqa: BLE001 - the narrative still stands without this
        return {"error": f"structured decision unavailable: {type(error).__name__}: {error}"}
