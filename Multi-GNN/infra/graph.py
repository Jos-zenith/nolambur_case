"""The transaction graph behind multi-hop queries (onboarding checks, follow-the-money).

  MemoryGraph  walks the engine's own in-process adjacency lists. Default; nothing to run.
  Neo4jGraph   write-through to Neo4j or Memgraph over Bolt. Every replayed / ingested
               transfer becomes (:Account)-[:SENT]->(:Account); flag and freeze state is
               mirrored onto the nodes. The graph outlives the process, and analysts can
               run their own Cypher against it.

The detectors keep reading the engine's in-memory indexes: they run on every
transaction, and a network round trip per payment would cap throughput. The graph
store serves the traversals that fan out, where a database index earns its keep.
Writes are buffered and flushed once per tick, so Neo4j lags the console by at most
one tick (0.5 s).

Money only moves forward in time, so a path counts only if each hop happened at or
after the one before it. Blocked transfers (frozen endpoint) are not paths.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable

from . import settings

MAX_HOPS = 5


def summarize(paths: list[dict[str, Any]], origin: str) -> dict[str, Any]:
    by_depth: dict[int, set[str]] = defaultdict(set)
    for p in paths:
        for depth, node in enumerate(p["nodes"][1:], start=1):
            by_depth[depth].add(node["id"])
    reached = {n["id"] for p in paths for n in p["nodes"][1:]} - {origin}
    return {"accountsReached": len(reached), "byHop": [{"hop": d, "accounts": len(ids)} for d, ids in sorted(by_depth.items())]}


class MemoryGraph:
    backend = "memory"

    def __init__(self, adjacency: Callable[[], tuple[dict, dict]]):
        # adjacency() returns the engine's live (inbound, outbound) dicts of Row lists
        self._adjacency = adjacency
        self.error: str | None = None

    def describe(self) -> dict[str, Any]:
        _, outbound = self._adjacency()
        return {"backend": self.backend, "edges": sum(len(v) for v in outbound.values()), "persistent": False}

    def add(self, row) -> None:
        pass

    def mark(self, account_id: str, *, flagged: bool | None = None, frozen: bool | None = None) -> None:
        pass

    def flush(self) -> None:
        pass

    def reset(self) -> None:
        pass

    def counterparties(self, account_id: str) -> set[str]:
        inbound, outbound = self._adjacency()
        return {x.from_id for x in inbound.get(account_id, [])} | {x.to_id for x in outbound.get(account_id, [])}

    def downstream_paths(self, account_id: str, hops: int, limit: int) -> list[dict[str, Any]]:
        _, outbound = self._adjacency()
        hops = max(1, min(hops, MAX_HOPS))
        paths: list[dict[str, Any]] = []

        def walk(node: str, after: float, nodes: list[dict], legs: list[dict], seen: set[str]) -> None:
            if len(paths) >= limit:
                return
            for x in outbound.get(node, []):
                if x.blocked or x.t < after or x.to_id in seen:
                    continue
                n2 = nodes + [{"id": x.to_id, "vpa": x.to_vpa}]
                l2 = legs + [{"amount": x.amount, "t": x.t, "row": x.row, "gnn": x.gnn}]
                paths.append({"nodes": n2, "legs": l2})
                if len(paths) >= limit:
                    return
                if len(l2) < hops:
                    walk(x.to_id, x.t, n2, l2, seen | {x.to_id})

        start = outbound.get(account_id, [])
        origin_vpa = start[0].from_vpa if start else account_id
        walk(account_id, float("-inf"), [{"id": account_id, "vpa": origin_vpa}], [], {account_id})
        return paths


class Neo4jGraph:
    backend = "neo4j"

    def __init__(self) -> None:
        from neo4j import GraphDatabase  # type: ignore  (pip install neo4j)

        self.driver = GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD))
        self.driver.verify_connectivity()
        self.ns = settings.NEO4J_NAMESPACE
        self._lock = threading.Lock()
        self._rows: list[dict[str, Any]] = []
        self._marks: dict[str, dict[str, Any]] = {}
        self.written = 0
        self.error: str | None = None
        self._index()

    def _run(self, query: str, **params: Any) -> list[dict[str, Any]]:
        with self.driver.session() as session:
            return [r.data() for r in session.run(query, ns=self.ns, **params)]

    def _index(self) -> None:
        for statement in (
            "CREATE INDEX account_ns_id IF NOT EXISTS FOR (a:Account) ON (a.ns, a.id)",  # Neo4j 5
            "CREATE INDEX ON :Account(id)",  # Memgraph
        ):
            try:
                self._run(statement)
                return
            except Exception:
                continue

    def describe(self) -> dict[str, Any]:
        return {"backend": self.backend, "uri": settings.NEO4J_URI, "namespace": self.ns, "edgesWritten": self.written, "pending": len(self._rows), "persistent": True, "error": self.error}

    def add(self, row) -> None:
        with self._lock:
            self._rows.append(
                {"row": row.row, "t": row.t, "amount": row.amount, "gnn": row.gnn, "blocked": row.blocked, "source": row.source,
                 "from_id": row.from_id, "from_vpa": row.from_vpa, "from_state": row.from_state,
                 "to_id": row.to_id, "to_vpa": row.to_vpa, "to_state": row.to_state}
            )

    def mark(self, account_id: str, *, flagged: bool | None = None, frozen: bool | None = None) -> None:
        with self._lock:
            m = self._marks.setdefault(account_id, {"id": account_id})
            if flagged is not None:
                m["flagged"] = flagged
            if frozen is not None:
                m["frozen"] = frozen

    def flush(self) -> None:
        with self._lock:
            rows, self._rows = self._rows, []
            marks, self._marks = list(self._marks.values()), {}
        if not rows and not marks:
            return
        try:
            with self.driver.session() as session:
                for i in range(0, len(rows), 2000):
                    session.run(
                        """
                        UNWIND $rows AS r
                        MERGE (a:Account {ns: $ns, id: r.from_id}) ON CREATE SET a.vpa = r.from_vpa, a.state = r.from_state
                        MERGE (b:Account {ns: $ns, id: r.to_id}) ON CREATE SET b.vpa = r.to_vpa, b.state = r.to_state
                        CREATE (a)-[:SENT {row: r.row, t: r.t, amount: r.amount, gnn: r.gnn, blocked: r.blocked, source: r.source}]->(b)
                        """,
                        ns=self.ns, rows=rows[i : i + 2000],
                    ).consume()
                if marks:
                    session.run(
                        """
                        UNWIND $marks AS m
                        MATCH (a:Account {ns: $ns, id: m.id})
                        SET a.flagged = coalesce(m.flagged, a.flagged), a.frozen = coalesce(m.frozen, a.frozen)
                        """,
                        ns=self.ns, marks=marks,
                    ).consume()
            self.written += len(rows)
            self.error = None
        except Exception as error:
            self.error = f"{type(error).__name__}: {error}"[:300]
            with self._lock:  # put them back; the next tick retries
                self._rows = rows + self._rows
                for m in marks:
                    self._marks.setdefault(m["id"], {}).update({k: v for k, v in m.items()})

    def reset(self) -> None:
        with self._lock:
            self._rows, self._marks = [], {}
        while self._run("MATCH (a:Account {ns: $ns}) WITH a LIMIT 10000 DETACH DELETE a RETURN count(*) AS n")[0]["n"]:
            pass
        self.written = 0

    def counterparties(self, account_id: str) -> set[str]:
        rows = self._run("MATCH (:Account {ns: $ns, id: $id})-[:SENT]-(b:Account) RETURN DISTINCT b.id AS id", id=account_id)
        return {r["id"] for r in rows}

    def downstream_paths(self, account_id: str, hops: int, limit: int) -> list[dict[str, Any]]:
        hops = max(1, min(int(hops), MAX_HOPS))  # variable-length bounds cannot be parameters
        query = f"""
            MATCH p = (a:Account {{ns: $ns, id: $id}})-[:SENT*1..{hops}]->(:Account)
            WHERE all(i IN range(0, size(relationships(p)) - 2) WHERE relationships(p)[i].t <= relationships(p)[i + 1].t)
              AND none(r IN relationships(p) WHERE r.blocked)
            RETURN [n IN nodes(p) | {{id: n.id, vpa: n.vpa}}] AS nodes,
                   [r IN relationships(p) | {{amount: r.amount, t: r.t, row: r.row, gnn: r.gnn}}] AS legs
            LIMIT $limit
        """
        # Cypher has no portable "distinct nodes in path" test (Neo4j's relationship
        # uniqueness still allows revisiting a node), so cycles are dropped here.
        rows = self._run(query, id=account_id, limit=int(limit) * 2)
        paths = [r for r in rows if len({n["id"] for n in r["nodes"]}) == len(r["nodes"])]
        return paths[:limit]


def make_graph(adjacency: Callable[[], tuple[dict, dict]]) -> tuple[Any, str | None]:
    """The configured graph, or MemoryGraph plus the reason Neo4j could not be used."""
    if settings.RAIL_GRAPH == "neo4j":
        try:
            return Neo4jGraph(), None
        except Exception as error:
            return MemoryGraph(adjacency), f"neo4j unavailable, using memory: {type(error).__name__}: {error}"[:300]
    return MemoryGraph(adjacency), None
