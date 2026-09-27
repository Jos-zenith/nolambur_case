"""CLI entry point.  Run from Multi-GNN/:

    python -m agents --self-test                 # shim + bridge checks, no Claude
    python -m agents --test-sms "message"        # exercise notify_officer, no Claude
    python -m agents --sample fraud              # run the orchestrator on a sample
    python -m agents --sample clean
    python -m agents --sender <vpa> --receiver <vpa> --amount 500000
    python -m agents --json '{"sender_vpa": "...", "receiver_vpa": "...", "amount_inr": 500000}'
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

from .config import ACTION_LOG, AGENTS_DIR, ORCHESTRATOR_MODEL
from . import bridge_client
from .nolambur_data import encode_timestamp
from .transaction_graph import transaction_to_predict_payload

_SAMPLES = json.loads((AGENTS_DIR / "sample_transactions.json").read_text(encoding="utf-8"))


def _self_test() -> int:
    print("1. transaction -> /predict payload shim")
    sample = _SAMPLES["fraud"]
    payload, context = transaction_to_predict_payload(
        sample["sender_vpa"], sample["receiver_vpa"], sample["amount_inr"], sample["timestamp"]
    )
    print(json.dumps(payload, indent=2))
    assert len(payload["edges"][0]["features"]) == 4, "edge feature vector must have 4 values"
    assert payload["node_account_ids"] == [
        context["sender"]["account_id"],
        context["receiver"]["account_id"],
    ]
    print("   sender/receiver resolved:", context["sender"]["account_id"], context["receiver"]["account_id"])

    print("2. timestamp encoding regression")
    encoded = encode_timestamp(datetime(2024, 3, 17, 5, 22, 7))
    print(f"   encode(2024-03-17T05:22:07) = {encoded}  (formatted_transactions.csv row 0 = 19337)")
    assert encoded == 19337, "timestamp encoding drifted from prepare_datasets.convert_nolambur"

    print("3. bridge round-trip")
    try:
        print("   /health:", json.dumps(bridge_client.health()))
        response = bridge_client.predict(payload)
        top = response.get("predictions", [{}])[0]
        print(
            f"   /predict: p={top.get('fraud_probability'):.4f}  "
            f"background_graph={response.get('scored_with_background_graph')}  "
            f"linked_accounts={response.get('linked_accounts')}  "
            f"normalized={response.get('normalized')}"
        )
    except bridge_client.BridgeUnavailable as error:
        print(f"   SKIPPED - {error}")

    print("\nself-test OK")
    return 0


def _build_transaction(args: argparse.Namespace) -> dict:
    if args.sample:
        transaction = dict(_SAMPLES[args.sample])
        transaction.pop("_note", None)
        return transaction
    if args.json:
        return json.loads(args.json)
    if args.sender and args.receiver and args.amount is not None:
        transaction = {
            "sender_vpa": args.sender,
            "receiver_vpa": args.receiver,
            "amount_inr": args.amount,
        }
        if args.timestamp:
            transaction["timestamp"] = args.timestamp
        return transaction
    raise SystemExit("provide --sample, or --json, or --sender/--receiver/--amount")


def _printer(kind: str, data: dict) -> None:
    if kind == "assistant":
        print(f"\n\033[36m[agent]\033[0m {data['text']}")
    elif kind == "tool_call":
        print(f"\033[33m  -> {data['name']}({json.dumps(data['input'])[:200]})\033[0m")
    elif kind == "tool_result":
        flag = " (error)" if data["is_error"] else ""
        print(f"\033[90m  <- {data['name']}{flag}: {data['content'][:400]}\033[0m")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agents", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-test", action="store_true", help="shim + bridge checks, no Claude call")
    parser.add_argument("--test-sms", metavar="TEXT", help="send one alert via notify_officer and exit")
    parser.add_argument("--sample", choices=sorted(k for k in _SAMPLES))
    parser.add_argument("--json", help="transaction as a JSON object")
    parser.add_argument("--sender")
    parser.add_argument("--receiver")
    parser.add_argument("--amount", type=float)
    parser.add_argument("--timestamp")
    parser.add_argument("--model", default=ORCHESTRATOR_MODEL, help=f"default: {ORCHESTRATOR_MODEL}")
    parser.add_argument("--max-iterations", type=int, default=12)
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    if args.test_sms:
        from .tools_impl import notify_officer

        print(json.dumps(notify_officer(args.test_sms, priority="high"), indent=2))
        return 0

    transaction = _build_transaction(args)

    try:
        import anthropic
    except ImportError:
        print("The orchestrator needs the Anthropic SDK:\n  pip install -r agents/requirements.txt")
        return 1
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        print("No credentials found. Set ANTHROPIC_API_KEY (or run `ant auth login`).")
        return 1

    from .orchestrator import run

    print(f"model: {args.model}\ntransaction: {json.dumps(transaction)}\n" + "-" * 72)
    try:
        result = run(transaction, model=args.model, max_iterations=args.max_iterations, on_event=_printer)
    except anthropic.AuthenticationError:
        print("\nAnthropic rejected the credentials (401). Check ANTHROPIC_API_KEY.")
        return 1
    except anthropic.BadRequestError as error:
        message = getattr(error, "message", str(error))
        if "credit balance" in message.lower():
            print("\nThe API key has no credit balance. Add credits at console.anthropic.com "
                  "(Plans & Billing), then re-run.")
        else:
            print(f"\nAnthropic rejected the request (400): {message}")
        return 1
    except anthropic.APIStatusError as error:
        print(f"\nAnthropic API error ({error.status_code}): {getattr(error, 'message', error)}")
        return 1
    except anthropic.APIConnectionError:
        print("\nCould not reach the Anthropic API. Check the network connection.")
        return 1

    print("\n" + "=" * 72 + "\nCASE DECISION\n" + "=" * 72)
    print(json.dumps(result["decision"], indent=2))
    if ACTION_LOG.exists():
        print(f"\nActions recorded in {ACTION_LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
