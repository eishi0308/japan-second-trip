"""Where Next planner: deterministic filtering, scoring and option selection.

Pure code over plain dataclasses. The repository adapter
(``db/repositories/planner_repo.py``) loads the M1 catalogue into a
``Catalogue``; ``engine.plan`` turns traveller conditions into three options
(Classic / Unexpected / Slow-paced), a "Not for this trip" list and the real
filtering counts. No LLM call happens here: the same conditions always give
the same answer, which is what lets the Compare screen's what-if toggles
recompute instantly.
"""
