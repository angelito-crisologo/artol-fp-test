"""Phase C.2 — LLM-authored topology layer.

The deterministic part (CP-SAT solver, validator, renderer) lives in phase_c/
and is reused here unchanged. What this subpackage adds is the layer that
*produces* the topology: takes a user brief (natural-language intent +
structured lot info), asks an LLM to author an adjacency graph in our
existing topology schema, validates it, and hands it to the solver.

The LLM client is pluggable — there's a stub mode (keyword-based selection
from the hand-authored exemplars) for development and tests, and a Claude
mode that calls the Anthropic API when an API key is present. The pipeline
below the LLM is identical in both modes.
"""
