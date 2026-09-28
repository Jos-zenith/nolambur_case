from __future__ import annotations

import json
import os
import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import torch
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from models import GATe, GINe, PNA, RGCN


SCRIPT_DIR = Path(__file__).resolve().parent


class GraphEdge(BaseModel):
    source: int = Field(..., ge=0)
    target: int = Field(..., ge=0)
    features: list[float]
    edge_type: int | None = Field(default=None, ge=0)


class InferenceRequest(BaseModel):
    model: Literal["gin", "gat", "pna", "rgcn"] = "gin"
    node_features: list[list[float]]
    edges: list[GraphEdge]
    node_account_ids: list[str | None] | None = Field(
        default=None,
        description=(
            "Optional, one entry per node_features row: a real Nolambur account id "
            "(matches nolambur_transactions.csv's sender_id/recv_id). A node whose id "
            "matches an account already in the background graph is scored plugged into "
            "its real position and real neighbors there. A node with no id, or an id "
            "that doesn't match, is scored as a genuinely new account with no history -- "
            "still attached to the same background graph via this request's own edges, "
            "just without any of that account's real prior transactions as context."
        ),
    )


class InferenceResponse(BaseModel):
    model: str
    checkpoint_loaded: bool
    edge_count: int
    predictions: list[dict[str, Any]]
    normalized: bool = False
    scored_with_background_graph: bool = False
    linked_accounts: int = 0


SUPPORTED_MODELS = frozenset({"gin", "gat", "pna", "rgcn"})


def _load_json(file_name: str) -> dict[str, Any]:
    with open(SCRIPT_DIR / file_name, "r", encoding="utf-8") as file:
        return json.load(file)


DATA_CONFIG = _load_json("data_config.json")
MODEL_SETTINGS = _load_json("model_settings.json")


def _resolve_norm_stats_path(checkpoint_path: Path) -> Path:
    # Sidecar written by finetune_local_nolambur.py next to its checkpoint,
    # e.g. models/local_finetuned_gin_nolambur.pt -> ...norm.json
    return checkpoint_path.with_suffix("").with_suffix(".norm.json")


@lru_cache(maxsize=2)
def _load_norm_stats(checkpoint_path_str: str) -> dict[str, Any] | None:
    norm_path = _resolve_norm_stats_path(Path(checkpoint_path_str))
    if not norm_path.exists():
        return None
    with open(norm_path, "r", encoding="utf-8") as file:
        return json.load(file)


def _resolve_checkpoint_path() -> Path:
    checkpoint_path = Path(DATA_CONFIG["paths"]["model_to_load"])
    if not checkpoint_path.is_absolute():
        checkpoint_path = (SCRIPT_DIR / checkpoint_path).resolve()
    return checkpoint_path


@lru_cache(maxsize=1)
def _load_background_graph() -> dict[str, Any] | None:
    """The full real Nolambur graph, in the exact node encoding the model
    trained on -- Multi-GNN/nolambur/formatted_transactions.csv (built by
    prepare_datasets.py) rather than the raw nolambur_transactions.csv.

    GINe aggregates over each node's neighborhood (n_gnn_layers=2 hops). A
    request built from just a handful of edges gives the model a tiny,
    sparse neighborhood it never saw at train/eval time -- a real, verified
    check found this alone (not the loss-weight/imbalance) is why isolated
    /predict calls over-flagged clean transactions: eval during training
    always scored edges within the *entire* graph as context (see
    TwoStageFinetuner._evaluate_stage, which clones the whole data object).
    Loading this once lets every request be spliced onto real, full-scale
    context instead of standing alone. `raw` carries the matching
    nolambur_transactions.csv rows (same order, same row count, one-to-one --
    guaranteed by prepare_datasets.py) for the human-readable fields (account
    ids, states, timestamps) the formatted file doesn't keep.
    """
    formatted_path = SCRIPT_DIR / "nolambur" / "formatted_transactions.csv"
    raw_path = SCRIPT_DIR / "nolambur_transactions.csv"
    if not formatted_path.exists() or not raw_path.exists():
        return None

    formatted = pd.read_csv(formatted_path)
    raw = pd.read_csv(raw_path)
    if len(formatted) != len(raw) or formatted.empty:
        return None

    n_nodes = int(max(formatted["from_id"].max(), formatted["to_id"].max())) + 1
    node_features = torch.ones((n_nodes, 1), dtype=torch.float32)
    edge_index = torch.tensor(formatted[["from_id", "to_id"]].to_numpy().T, dtype=torch.long)
    edge_attr_raw = torch.tensor(
        formatted[["Timestamp", "Amount Received", "Received Currency", "Payment Format"]].to_numpy(),
        dtype=torch.float32,
    )

    checkpoint_path = _resolve_checkpoint_path()
    norm_stats = _load_norm_stats(str(checkpoint_path))
    normalized = False
    edge_attr = edge_attr_raw
    if norm_stats is not None and len(norm_stats["edge_attr_mean"]) == edge_attr_raw.shape[1]:
        mean = torch.tensor(norm_stats["edge_attr_mean"], dtype=torch.float32)
        std = torch.tensor(norm_stats["edge_attr_std"], dtype=torch.float32)
        std = torch.where(std == 0, torch.ones_like(std), std)
        edge_attr = (edge_attr_raw - mean) / std
        normalized = True

    in_degree = torch.bincount(edge_index[1], minlength=n_nodes)
    out_degree = torch.bincount(edge_index[0], minlength=n_nodes)

    # raw and formatted are the same rows in the same order (guaranteed by
    # prepare_datasets.py), so zipping them recovers which background node
    # index each real account UUID landed on. This is what lets /predict
    # actually connect a request's known accounts into the real graph
    # instead of appending them as new, edge-less nodes that only *look*
    # spliced in (see the module note on account_to_node_index's use).
    account_to_node_index: dict[str, int] = {}
    for sender, recv, from_id, to_id in zip(
        raw["sender_id"], raw["recv_id"], formatted["from_id"], formatted["to_id"]
    ):
        account_to_node_index.setdefault(str(sender), int(from_id))
        account_to_node_index.setdefault(str(recv), int(to_id))

    return {
        "node_features": node_features,
        "edge_index": edge_index,
        "edge_attr": edge_attr,
        "normalized": normalized,
        "raw": raw,
        "in_degree": in_degree,
        "out_degree": out_degree,
        "account_to_node_index": account_to_node_index,
    }


def _score_background_graph(model_name: str = "gin") -> torch.Tensor | None:
    """Run the trained model once over the entire background graph and
    return each edge's fraud probability, aligned to background['raw']'s row
    order. Cached process-wide (module-level, not lru_cache, since the return
    value is a mutable tensor)."""
    background = _load_background_graph()
    if background is None:
        return None
    try:
        model, _ = _load_model(
            model_name,
            background["node_features"].shape[1],
            background["edge_attr"].shape[1],
            background["edge_index"],
            edge_types=None,
        )
    except HTTPException:
        return None
    with torch.no_grad():
        logits = model(background["node_features"], background["edge_index"], background["edge_attr"])
        return torch.softmax(logits, dim=-1)[:, 1]


_BACKGROUND_SCORES_CACHE: torch.Tensor | None = None
_BACKGROUND_SCORES_LOADED = False


def _load_background_scores() -> torch.Tensor | None:
    global _BACKGROUND_SCORES_CACHE, _BACKGROUND_SCORES_LOADED
    if not _BACKGROUND_SCORES_LOADED:
        _BACKGROUND_SCORES_CACHE = _score_background_graph()
        _BACKGROUND_SCORES_LOADED = True
    return _BACKGROUND_SCORES_CACHE


@lru_cache(maxsize=2)
def _load_checkpoint_state(checkpoint_path_str: str) -> dict[str, Any]:
    checkpoint_path = Path(checkpoint_path_str)
    checkpoint = torch.load(checkpoint_path, map_location="cpu")

    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        return checkpoint["model_state_dict"]

    if isinstance(checkpoint, dict):
        return checkpoint

    raise HTTPException(status_code=503, detail=f"Unsupported checkpoint format at {checkpoint_path}")


def _build_model(
    model_name: str,
    num_node_features: int,
    num_edge_features: int,
    edge_index: torch.Tensor,
    edge_types: torch.Tensor | None = None,
) -> torch.nn.Module:
    settings = MODEL_SETTINGS[model_name]["params"]
    hidden_size = int(round(settings["n_hidden"]))
    layers = int(round(settings["n_gnn_layers"]))
    dropout = float(settings["dropout"])
    final_dropout = float(settings["final_dropout"])
    edge_updates = os.getenv("GNN_EDGE_UPDATES", "false").lower() in {"1", "true", "yes"}

    if model_name == "gin":
        return GINe(
            num_features=num_node_features,
            num_gnn_layers=layers,
            n_classes=2,
            n_hidden=hidden_size,
            edge_updates=edge_updates,
            edge_dim=num_edge_features,
            dropout=dropout,
            final_dropout=final_dropout,
        )

    if model_name == "gat":
        n_heads = int(round(settings.get("n_heads", 4)))
        return GATe(
            num_features=num_node_features,
            num_gnn_layers=layers,
            n_classes=2,
            n_hidden=hidden_size,
            n_heads=n_heads,
            edge_updates=edge_updates,
            edge_dim=num_edge_features,
            dropout=dropout,
            final_dropout=final_dropout,
        )

    if model_name == "pna":
        degree = torch.bincount(edge_index[1], minlength=int(edge_index.max().item()) + 1 if edge_index.numel() else 1)
        if degree.numel() == 0:
            degree = torch.tensor([1], dtype=torch.long)
        return PNA(
            num_features=num_node_features,
            num_gnn_layers=layers,
            n_classes=2,
            n_hidden=hidden_size,
            edge_updates=edge_updates,
            edge_dim=num_edge_features,
            dropout=dropout,
            final_dropout=final_dropout,
            deg=degree,
        )

    if model_name == "rgcn":
        num_relations = int(edge_types.max().item()) + 1 if edge_types is not None and edge_types.numel() else int(os.getenv("GNN_RELATIONS", "8"))
        return RGCN(
            num_features=num_node_features,
            edge_dim=num_edge_features,
            num_relations=num_relations,
            num_gnn_layers=layers,
            n_classes=2,
            n_hidden=hidden_size,
            edge_update=edge_updates,
            dropout=dropout,
            final_dropout=final_dropout,
            n_bases=int(os.getenv("GNN_RGCN_BASES", "8")),
        )

    raise HTTPException(status_code=400, detail=f"Unsupported model: {model_name}")


def _load_model(
    model_name: str,
    num_node_features: int,
    num_edge_features: int,
    edge_index: torch.Tensor,
    edge_types: torch.Tensor | None = None,
) -> tuple[torch.nn.Module, Path]:
    model = _build_model(model_name, num_node_features, num_edge_features, edge_index, edge_types=edge_types)
    checkpoint_path = _resolve_checkpoint_path()

    if not checkpoint_path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Checkpoint not found at {checkpoint_path}",
        )

    state_dict = _load_checkpoint_state(str(checkpoint_path))
    model.load_state_dict(state_dict)
    model.eval()
    return model, checkpoint_path


def _tensorize_request(
    request: InferenceRequest,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor | None, int]:
    if not request.edges:
        raise HTTPException(status_code=422, detail="edges must not be empty")
    if not request.node_features:
        raise HTTPException(status_code=422, detail="node_features must not be empty")

    try:
        node_features = torch.tensor(request.node_features, dtype=torch.float32)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=f"node_features must be a rectangular float matrix: {error}") from error

    sources = torch.tensor([edge.source for edge in request.edges], dtype=torch.long)
    targets = torch.tensor([edge.target for edge in request.edges], dtype=torch.long)
    edge_index = torch.stack([sources, targets], dim=0)

    edge_rows: list[list[float]] = []
    edge_types: list[int] = []
    for index, edge in enumerate(request.edges):
        edge_row = [float(index)] + [float(value) for value in edge.features]
        if request.model == "rgcn":
            if edge.edge_type is None:
                raise HTTPException(status_code=422, detail="rgcn requests must include edge_type for each edge")
            edge_row.append(float(edge.edge_type))
            edge_types.append(edge.edge_type)
        edge_rows.append(edge_row)

    try:
        edge_features = torch.tensor(edge_rows, dtype=torch.float32)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=f"edges.features must be a rectangular float matrix: {error}") from error

    if node_features.ndim != 2:
        raise HTTPException(status_code=422, detail="node_features must be a 2D matrix")
    if edge_index.ndim != 2 or edge_index.shape[0] != 2:
        raise HTTPException(status_code=422, detail="edges must define a valid 2-column graph edge list")
    if edge_index.numel() and int(edge_index.max().item()) >= node_features.shape[0]:
        raise HTTPException(status_code=422, detail="edge endpoints reference nodes outside node_features")

    edge_type_tensor = torch.tensor(edge_types, dtype=torch.long) if edge_types else None
    return node_features, edge_index, edge_features, edge_type_tensor, edge_features.shape[1] - 1


def _predict_edges(request: InferenceRequest) -> InferenceResponse:
    node_features, edge_index, edge_features, edge_types, raw_edge_feature_count = _tensorize_request(request)

    # The model was trained on z-normalized edge features ((x - mean) / std
    # per column, computed from the training split -- see data_loading.py).
    # A checkpoint's weights only make sense for inputs on that same scale,
    # so raw request values must be normalized the same way before being fed
    # in, using the stats saved alongside the checkpoint at training time.
    # Without that sidecar file, predictions are run on unnormalized,
    # out-of-distribution-scale inputs -- real inference, not mocked, but not
    # meaningful either, so callers are told via `normalized` in the response.
    edge_semantic_features = edge_features[:, 1:]
    checkpoint_path = _resolve_checkpoint_path()
    norm_stats = _load_norm_stats(str(checkpoint_path))
    normalized = False
    if norm_stats is not None:
        mean = torch.tensor(norm_stats["edge_attr_mean"], dtype=torch.float32)
        std = torch.tensor(norm_stats["edge_attr_std"], dtype=torch.float32)
        std = torch.where(std == 0, torch.ones_like(std), std)
        if mean.numel() == edge_semantic_features.shape[1]:
            edge_semantic_features = (edge_semantic_features - mean) / std
            normalized = True

    # Splice the request's own nodes/edges onto the real background graph and
    # score them there, rather than as an isolated standalone graph -- see
    # _load_background_graph's docstring for why an isolated request graph
    # alone under-performs. Only "gin" has a locally-trained checkpoint/
    # background to splice onto; other models fall back to scoring the
    # request in isolation, same as before.
    #
    # Just concatenating the request's tensors onto the background's doesn't
    # by itself connect anything -- request node indices are request-local
    # (0..n-1), so appended verbatim they land as a brand-new, edge-less
    # island with no path to the background graph at all; message passing
    # would never carry any real context into it. node_account_ids is what
    # actually closes that gap: a request node naming a real background
    # account is remapped onto *that account's own existing node index*, so
    # it inherits its real neighbors; only genuinely new/unnamed accounts get
    # appended as fresh nodes.
    background = _load_background_graph() if request.model == "gin" else None
    used_background = False
    linked_accounts = 0

    if background is not None:
        account_to_node = background["account_to_node_index"]
        account_ids = request.node_account_ids or []
        n_bg = background["node_features"].shape[0]

        final_index_of: list[int] = []
        new_feature_rows: list[torch.Tensor] = []
        next_new_index = n_bg
        for i in range(node_features.shape[0]):
            account_id = account_ids[i] if i < len(account_ids) else None
            bg_index = account_to_node.get(account_id) if account_id else None
            if bg_index is not None:
                final_index_of.append(bg_index)
                linked_accounts += 1
            else:
                final_index_of.append(next_new_index)
                new_feature_rows.append(node_features[i])
                next_new_index += 1

        remap = torch.tensor(final_index_of, dtype=torch.long)
        remapped_edge_index = remap[edge_index]

        combined_node_features = (
            torch.cat([background["node_features"], torch.stack(new_feature_rows, dim=0)], dim=0)
            if new_feature_rows else background["node_features"]
        )
        combined_edge_index = torch.cat([background["edge_index"], remapped_edge_index], dim=1)
        combined_edge_attr = torch.cat([background["edge_attr"], edge_semantic_features], dim=0)

        model, checkpoint_path = _load_model(
            request.model, combined_node_features.shape[1], combined_edge_attr.shape[1],
            combined_edge_index, edge_types=edge_types,
        )
        with torch.no_grad():
            logits = model(combined_node_features, combined_edge_index, combined_edge_attr)
            probabilities = torch.softmax(logits, dim=-1)[-edge_semantic_features.shape[0]:]
        normalized = normalized and background["normalized"]
        used_background = True
    else:
        model, checkpoint_path = _load_model(
            request.model, node_features.shape[1], raw_edge_feature_count, edge_index, edge_types=edge_types,
        )
        with torch.no_grad():
            logits = model(node_features, edge_index, edge_semantic_features)
            probabilities = torch.softmax(logits, dim=-1)

    predictions: list[dict[str, Any]] = []
    for index, edge in enumerate(request.edges):
        predictions.append(
            {
                "edge_index": index,
                "source": edge.source,
                "target": edge.target,
                "fraud_probability": float(probabilities[index, 1].item()),
                "predicted_label": int(probabilities[index].argmax(dim=-1).item()),
            }
        )

    predictions.sort(key=lambda item: item["fraud_probability"], reverse=True)

    return InferenceResponse(
        model=request.model,
        checkpoint_loaded=checkpoint_path.exists(),
        edge_count=len(predictions),
        predictions=predictions,
        normalized=normalized,
        scored_with_background_graph=used_background,
        linked_accounts=linked_accounts,
    )


app = FastAPI(title="GNN Inference Bridge", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("GNN_CORS_ORIGINS", "http://localhost:3000").split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "gnn-inference-bridge",
        "supported_models": sorted(SUPPORTED_MODELS),
    }


@app.get("/health")
def health() -> dict[str, Any]:
    checkpoint_path = _resolve_checkpoint_path()
    return {
        "status": "ok",
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_exists": checkpoint_path.exists(),
        "available_models": sorted(MODEL_SETTINGS.keys()),
    }


@app.post("/predict", response_model=InferenceResponse)
def predict(request: InferenceRequest) -> InferenceResponse:
    return _predict_edges(request)


_REPLAY_FEED_CACHE: list[dict[str, Any]] | None = None


def _build_replay_feed(sample_size: int = 24) -> list[dict[str, Any]]:
    """Score a real slice of the Nolambur synthetic data with the trained model.

    This used to be a fixed 3-item list of hand-written numbers, looped
    forever -- a mock baked into the backend itself, not a frontend fallback.
    Every field below instead comes from an actual nolambur_transactions.csv
    row (real account ids, real states, real timestamps, real amounts), and
    muleScore is that row's actual prediction from a single full-graph
    forward pass (_load_background_scores) -- the same context the model was
    trained and evaluated with, not an isolated small subgraph reconstructed
    per event. It is still a *replay* of historical synthetic transactions on
    a loop, not a live production feed -- callers are told that explicitly
    via `source` on every event. inVelocity/outVelocity are the account's
    real in/out-degree across the *entire* background graph, normalized by
    the graph's max degree -- a real, if simplified, structural signal, not
    the windowed multi-minute velocity described in the README's Mule Pulse
    section.
    """
    global _REPLAY_FEED_CACHE
    if _REPLAY_FEED_CACHE is not None:
        return _REPLAY_FEED_CACHE

    background = _load_background_graph()
    scores = _load_background_scores()
    if background is None or scores is None:
        _REPLAY_FEED_CACHE = []
        return _REPLAY_FEED_CACHE

    raw = background["raw"]
    fraud_positions = raw.index[raw["is_fraud"] == 1][: sample_size // 2]
    clean_pool = raw.index[raw["is_fraud"] == 0]
    clean_needed = min(max(sample_size - len(fraud_positions), 0), len(clean_pool))
    clean_positions = pd.Index(clean_pool).to_series().sample(n=clean_needed, random_state=7).index

    chosen = sorted(list(fraud_positions) + list(clean_positions), key=lambda i: raw.loc[i, "timestamp"])
    if not chosen:
        _REPLAY_FEED_CACHE = []
        return _REPLAY_FEED_CACHE

    in_degree = background["in_degree"]
    out_degree = background["out_degree"]
    max_degree = max(int(in_degree.max().item()), int(out_degree.max().item()), 1)
    formatted = pd.read_csv(SCRIPT_DIR / "nolambur" / "formatted_transactions.csv")

    feed: list[dict[str, Any]] = []
    for i, row_pos in enumerate(chosen):
        row = raw.loc[row_pos]
        mule_score = float(scores[row_pos].item())
        to_id = int(formatted.loc[row_pos, "to_id"])
        from_id = int(formatted.loc[row_pos, "from_id"])
        if mule_score >= 0.9:
            label = "High mule probability"
        elif mule_score >= 0.6:
            label = "Elevated risk"
        else:
            label = "Nominal"
        feed.append({
            "id": f"replay-{i:03d}",
            "accountId": str(row["recv_id"]),
            "label": label,
            "muleScore": round(mule_score, 4),
            "inVelocity": round(int(in_degree[to_id].item()) / max_degree, 3),
            "outVelocity": round(int(out_degree[from_id].item()) / max_degree, 3),
            "geoMismatch": bool(row["sender_state"] != row["recv_state"]),
            "statePair": f"{row['sender_state']} → {row['recv_state']}",
            "timestamp": row["timestamp"],
            "source": "nolambur_synthetic_replay",
            "modelScored": background["normalized"],
            "scoredWithBackgroundGraph": True,
        })

    _REPLAY_FEED_CACHE = feed
    return feed


@app.get("/stream")
async def stream() -> StreamingResponse:
    async def event_generator():
        feed = _build_replay_feed()
        if not feed:
            yield f"data: {json.dumps({'error': 'no replay data available -- nolambur_transactions.csv or checkpoint missing'})}\n\n"
            return

        index = 0
        while True:
            yield f"data: {json.dumps(feed[index % len(feed)])}\n\n"
            index += 1
            await asyncio.sleep(1.8)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
        },
    )


def _rail_load() -> tuple[pd.DataFrame, torch.Tensor]:
    background = _load_background_graph()
    scores = _load_background_scores()
    if background is None or scores is None:
        raise RuntimeError("nolambur/formatted_transactions.csv, nolambur_transactions.csv or the checkpoint is missing")
    return background["raw"], scores


def _rail_predict_chain(legs: list[dict[str, Any]]) -> dict[str, Any]:
    """Score a transfer chain live through /predict's splice path (agents.transaction_graph builds the payload)."""
    from agents.transaction_graph import chain_to_predict_payload

    payload, context = chain_to_predict_payload(
        [{key: leg[key] for key in ("sender", "receiver", "amount_inr", "timestamp")} for leg in legs]
    )
    response = _predict_edges(InferenceRequest(**payload))
    by_edge = {item["edge_index"]: item for item in response.predictions}
    return {
        "legs": [{**leg, "fraud_probability": by_edge[i]["fraud_probability"]} for i, leg in enumerate(context["legs"])],
        "nodes": context["nodes"],
        "scoredWithBackgroundGraph": response.scored_with_background_graph,
        "linkedAccounts": response.linked_accounts,
        "normalized": response.normalized,
    }


import rail_engine  # noqa: E402  (needs the app and helpers above)

RAIL = rail_engine.mount(app, _rail_load, _rail_predict_chain)


if __name__ == "__main__":
    import uvicorn
    from threading import Thread
    from time import sleep
    from urllib.request import urlopen

    def keep_alive() -> None:
        health_url = os.getenv("GNN_KEEP_ALIVE_URL", "https://vict.onrender.com/health")
        while True:
            sleep(600)
            try:
                with urlopen(health_url, timeout=5):
                    pass
            except Exception:
                pass

    Thread(target=keep_alive, daemon=True).start()

    uvicorn.run(
        "bridge_api:app",
        host=os.getenv("GNN_HOST", "0.0.0.0"),
        port=int(os.getenv("GNN_PORT", os.getenv("PORT", "8001"))),
        reload=os.getenv("GNN_RELOAD", "false").lower() in {"1", "true", "yes"},
    )