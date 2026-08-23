"""Live research control flags. Not scores. Not GO.

Single SoT for stop/apply/wave. ``eval_tracks`` and
``combo_basket_catalog`` re-export. Flip only with a dated brief.
"""

EVENT_THREE_AND_PLUS_N_STOPPED: bool = True
CATALOG_AND_PLUS_N_STOPPED: bool = True
# Freeze identity n (compiled map), not a YAML file count. Name is historical; do not rename (callers pin it).
# yaml n>0 must equal this; yaml n==0 requires compiled n match. Do not add YAML.
CATALOG_YAML_COUNT_AT_STOP: int = 2254
RECONSTITUTION_APPLY: bool = False
CURRENT_EVAL_WAVE: str = "20260824ev"
