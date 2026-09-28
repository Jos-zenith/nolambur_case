"""Platform adapters for the rail engine: ingest, graph store, persistence, integrations.

Each piece has a default that runs locally with no extra services and a production
backend chosen by env var; see infra/settings.py for the full list.
"""
