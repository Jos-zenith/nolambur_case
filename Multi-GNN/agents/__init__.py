"""Operation Nolambur - multi-agent fraud-interception orchestrator.

A thin end-to-end slice: Claude runs the coordination loop (detect -> investigate
-> coordinate -> monitor) over tools that wrap the real GNN inference bridge
(`bridge_api.py`) and the real Nolambur synthetic dataset. Freeze / 1930-report /
NPCI-registry tools are simulated and clearly labelled as such.

Entry point: `python -m agents --help` (run from Multi-GNN/).
"""
