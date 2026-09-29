"""Which backend each platform piece uses. Everything is env-driven, and every default
runs on this machine with no extra services.

    RAIL_SOURCE            webhook (default) | kafka | kinesis | replay
                           webhook - live: the clock is event time from incoming payments, which
                                     arrive on POST /rail/ingest/payments. Nothing is replayed.
                           kafka / kinesis - as webhook, plus a consumer on the topic / stream.
                           replay  - demo and evaluation: nolambur_transactions.csv drives the clock
                                     with full-graph GNN scores; webhook payments join at the replay clock.
    RAIL_WEBHOOK_SECRET    if set, ingest requests must carry X-Nolambur-Signature: sha256=<hmac>
    KAFKA_BOOTSTRAP        e.g. localhost:9092          (pip install aiokafka)
    KAFKA_TOPIC            default upi.payments
    KAFKA_GROUP            default nolambur-rail
    KAFKA_OFFSET_RESET     earliest (default) | latest: where a new consumer group starts
    KINESIS_STREAM         stream name                  (pip install boto3; AWS creds from env)
    KINESIS_START          TRIM_HORIZON (default) | LATEST: where a shard with no checkpoint starts
    KINESIS_ENDPOINT       override the AWS endpoint (LocalStack, moto, a VPC endpoint)
    AWS_REGION             default ap-south-1

    MCA_PROVIDER           none (default) | http: live company/director lookups (infra/registry.py)
    MCA_API_URL            base URL of the lookup service (GET {url}/companies/{cin})
    MCA_API_KEY            sent as Authorization: Bearer <key>

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
    NOLAMBUR_DATASET       v2 (default) | v1: which dataset the engine replays and evaluates on
    RAIL_AUTO_HOLD         on (default) | off: the decision router applies graded restrictions (off = alert only)
    RAIL_ANALYSTS          default 2: team size for the alerts-per-analyst-per-day figure
    RAIL_SCORING           exact (default) | cached: live GNN scoring (infra/scorer.py); cached is ~3x faster
                           under load and within 0.02 of exact on v2 (reports/scorer_compare.json)
    RAIL_SCORING_REFRESH   cached mode: event-time seconds between embedding refreshes (default 300)
    BRIDGE_PUBLIC_URL      how the outbox reaches the bridge; default http://127.0.0.1:<GNN_PORT or 8001>
"""

from __future__ import annotations

import os
from pathlib import Path

MULTI_GNN_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = MULTI_GNN_DIR / "data"


def _load_dotenv(path: Path) -> None:
    """KEY=VALUE lines from Multi-GNN/.env (git-ignored) for local runs. Variables already
    set in the environment win, so a host's settings (Render) are never overridden."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(MULTI_GNN_DIR / ".env")

# Same port resolution as bridge_api.py's uvicorn.run: GNN_PORT, else the host's PORT (Render sets it), else 8001.
_PORT = os.getenv("GNN_PORT") or os.getenv("PORT") or "8001"
BRIDGE_PUBLIC_URL = os.getenv("BRIDGE_PUBLIC_URL", f"http://127.0.0.1:{_PORT}").rstrip("/")

RAIL_SOURCE = os.getenv("RAIL_SOURCE", "webhook").lower()
RAIL_WEBHOOK_SECRET = os.getenv("RAIL_WEBHOOK_SECRET", "")
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "upi.payments")
KAFKA_GROUP = os.getenv("KAFKA_GROUP", "nolambur-rail")
KAFKA_OFFSET_RESET = os.getenv("KAFKA_OFFSET_RESET", "earliest").lower()
KINESIS_STREAM = os.getenv("KINESIS_STREAM", "")
KINESIS_START = os.getenv("KINESIS_START", "TRIM_HORIZON").upper()
KINESIS_ENDPOINT = os.getenv("KINESIS_ENDPOINT", "")
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

RAIL_GRAPH = os.getenv("RAIL_GRAPH", "memory").lower()
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_NAMESPACE = os.getenv("NEO4J_NAMESPACE", "nolambur")

def _db_url(url: str) -> str:
    """Hosts hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the psycopg driver named."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


RAIL_DB_URL = _db_url(os.getenv("RAIL_DB_URL") or os.getenv("DATABASE_URL") or f"sqlite:///{(DATA_DIR / 'rail.db').as_posix()}")
# Render (and most PaaS) disks are wiped on redeploy: SQLite there loses the audit trail.
EPHEMERAL_DISK = bool(os.getenv("RENDER") or os.getenv("DYNO") or os.getenv("K_SERVICE"))

GATEWAY_WEBHOOK_URL = os.getenv("GATEWAY_WEBHOOK_URL", f"{BRIDGE_PUBLIC_URL}/sandbox/gateway/webhooks")
GATEWAY_WEBHOOK_SECRET = os.getenv("GATEWAY_WEBHOOK_SECRET", "sandbox-secret")
CFCFRMS_URL = os.getenv("CFCFRMS_URL", f"{BRIDGE_PUBLIC_URL}/sandbox/cfcfrms").rstrip("/")
NPCI_REGISTRY_URL = os.getenv("NPCI_REGISTRY_URL", f"{BRIDGE_PUBLIC_URL}/sandbox/npci").rstrip("/")

MCA_PROVIDER = os.getenv("MCA_PROVIDER", "none").lower()
MCA_API_URL = os.getenv("MCA_API_URL", "").rstrip("/")
MCA_API_KEY = os.getenv("MCA_API_KEY", "")

NOLAMBUR_DATASET = os.getenv("NOLAMBUR_DATASET", "v2").lower()
RAIL_SCORING = os.getenv("RAIL_SCORING", "exact").lower()  # exact | cached (layer-1 embeddings refreshed every RAIL_SCORING_REFRESH s)
RAIL_SCORING_REFRESH = float(os.getenv("RAIL_SCORING_REFRESH", "300"))  # v2: 10 days, temporal split; v1: the original 3-day file

RAIL_AUTO_HOLD = os.getenv("RAIL_AUTO_HOLD", "on").lower() not in ("off", "0", "false", "no")


def is_sandbox(url: str) -> bool:
    return url.startswith(BRIDGE_PUBLIC_URL + "/sandbox/")
