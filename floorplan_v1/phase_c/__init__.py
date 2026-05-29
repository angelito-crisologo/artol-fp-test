"""Phase C.1 — geometric solver from a hand-authored adjacency graph.

This subpackage is intentionally isolated from the Phase A templates. It reuses
the existing model/rules/validator/render code but introduces a new path:
    topology (adjacency graph) + lot -> CP-SAT solver -> Layout -> validator -> render

The Phase A templates and the generate.py pipeline are untouched.
"""
