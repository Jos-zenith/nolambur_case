from __future__ import annotations

import json
import os
import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

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


class InferenceResponse(BaseModel):
    model: str
    checkpoint_loaded: bool
    edge_count: int
    predictions: list[dict[str, Any]]


SUPPORTED_MODELS = frozenset({"gin", "gat", "pna", "rgcn"})


def _load_json(file_name: str) -> dict[str, Any]:
    with open(SCRIPT_DIR / file_name, "r", encoding="utf-8") as file:
        return json.load(file)


DATA_CONFIG = _load_json("data_config.json")
MODEL_SETTINGS = _load_json("model_settings.json")


def _resolve_checkpoint_path() -> Path:
    checkpoint_path = Path(DATA_CONFIG["paths"]["model_to_load"])
    if not checkpoint_path.is_absolute():
        checkpoint_path = (SCRIPT_DIR / checkpoint_path).resolve()
    return checkpoint_path


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
    model, checkpoint_path = _load_model(request.model, node_features.shape[1], raw_edge_feature_count, edge_index, edge_types=edge_types)

    with torch.no_grad():
        logits = model(node_features, edge_index, edge_features[:, 1:])
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


@app.get("/stream")
async def stream() -> StreamingResponse:
    async def event_generator():
        feed = [
            {
                "id": "pulse-001",
                "accountId": "MU-0047",
                "label": "Haridwar mule flagged",
                "muleScore": 0.95,
                "inVelocity": 0.31,
                "outVelocity": 0.84,
                "geoMismatch": True,
                "statePair": "TN → UK",
                "timestamp": "2026-05-20T08:14:00Z",
            },
            {
                "id": "pulse-002",
                "accountId": "AG-0012",
                "label": "Aggregator surge",
                "muleScore": 0.98,
                "inVelocity": 0.84,
                "outVelocity": 0.96,
                "geoMismatch": True,
                "statePair": "RJ → DL",
                "timestamp": "2026-05-20T08:24:00Z",
            },
            {
                "id": "pulse-003",
                "accountId": "BEN-0001",
                "label": "Beneficiary exit detected",
                "muleScore": 0.99,
                "inVelocity": 0.93,
                "outVelocity": 0.99,
                "geoMismatch": True,
                "statePair": "DL → exit",
                "timestamp": "2026-05-20T08:25:20Z",
            },
        ]

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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "bridge_api:app",
        host=os.getenv("GNN_HOST", "0.0.0.0"),
        port=int(os.getenv("GNN_PORT", "8001")),
        reload=os.getenv("GNN_RELOAD", "false").lower() in {"1", "true", "yes"},
    )