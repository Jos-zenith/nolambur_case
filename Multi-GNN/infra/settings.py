"""Which backend each platform piece uses. Everything is env-driven, and every default
runs on this machine with no extra services.

    RAIL_SOURCE            replay (default) | webhook | kafka | kinesis
                           replay  - the CSV replay drives the clock; POST /rail/ingest/payments
                                     still works and injects payments at the replay clock.
                           webhook - no replay; the clock is event time from incoming payments.
                           kafka / kinesis - as webhook, plus a consumer on the topic / stream.
    RAIL_WEBHOOK_SECRET    if set, ingest requests must carry X-Nolambur-Signature: sha256=<hmac>
    KAFKA_BOOTSTRAP        e.g. localhost:9092          (pip install aiokafka)
    KAFKA_TOPIC            default upi.payments
    KAFKA_GROUP            default nolambur-rail
    KINESIS_STREAM         stream name                  (pip install boto3; AWS creds from env)
    AWS_REGION             default ap-south-1

    RAIL_GRAPH             memory (default) | neo4j     (neo4j also covers Memgraph: both speak Bolt)
    NEO4J_URI              default bolt://localhost:7687 (pip install neo4j)
    NEO4J_USER / NEO4J_PASSWORD
    NEO4J_NAMESPACE        default nolambur; nodes carry it so several consoles can share a database

    RAIL_DB_URL            default sqlite:///<Multi-GNN>/data/rail.db
                           Postgres: postgresql+psycopg://user:pass@host/db (pip install "psycopg[binary]")

    GATEWAY_WEBHOOK_URL    where freeze instructions go; default is the bridge's own mock gateway
    GATEWAY_WEBHOOK_SECRET HMAC key for those webhooks; default "sandbox-secret"
    CFCFRMS_URL            1930 portal base URL; default is the bridge's own mock portal
    NPCI_REGISTRY_URL      suspect-registry base URL; default is the bridge's own mock registry
    RAIL_AUTO_HOLD         on (default) | off: hold accounts on critical alerts the model also scores >= 0.9
    BRIDGE_PUBLIC_URL      how the outbox reaches the bridge; default http://127.0.0.1:<GNN_PORT or 8001>
"""

from __future__ import annotations

import os
from pathlib import Path

MULTI_GNN_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = MULTI_GNN_DIR / "data"

# Same port resolution as bridge_api.py's uvicorn.run: GNN_PORT, else the host's PORT (Render sets it), else 8001.
_PORT = os.getenv("GNN_PORT") or os.getenv("PORT") or "8001"
BRIDGE_PUBLIC_URL = os.getenv("BRIDGE_PUBLIC_URL", f"http://127.0.0.1:{_PORT}").rstrip("/")

RAIL_SOURCE = os.getenv("RAIL_SOURCE", "replay").lower()
RAIL_WEBHOOK_SECRET = os.getenv("RAIL_WEBHOOK_SECRET", "")
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "upi.payments")
KAFKA_GROUP = os.getenv("KAFKA_GROUP", "nolambur-rail")
KINESIS_STREAM = os.getenv("KINESIS_STREAM", "")
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

RAIL_GRAPH = os.getenv("RAIL_GRAPH", "memory").lower()
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_NAMESPACE = os.getenv("NEO4J_NAMESPACE", "nolambur")

RAIL_DB_URL = os.getenv("RAIL_DB_URL", f"sqlite:///{(DATA_DIR / 'rail.db').as_posix()}")

GATEWAY_WEBHOOK_URL = os.getenv("GATEWAY_WEBHOOK_URL", f"{BRIDGE_PUBLIC_URL}/sandbox/gateway/webhooks")
GATEWAY_WEBHOOK_SECRET = os.getenv("GATEWAY_WEBHOOK_SECRET", "sandbox-secret")
CFCFRMS_URL = os.getenv("CFCFRMS_URL", f"{BRIDGE_PUBLIC_URL}/sandbox/cfcfrms").rstrip("/")
NPCI_REGISTRY_URL = os.getenv("NPCI_REGISTRY_URL", f"{BRIDGE_PUBLIC_URL}/sandbox/npci").rstrip("/")

RAIL_AUTO_HOLD = os.getenv("RAIL_AUTO_HOLD", "on").lower() not in ("off", "0", "false", "no")


def is_sandbox(url: str) -> bool:
    return url.startswith(BRIDGE_PUBLIC_URL + "/sandbox/")
