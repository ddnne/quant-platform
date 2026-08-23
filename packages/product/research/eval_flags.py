"""Live research control flags. Not scores. Not GO.

Single SoT for stop/apply/wave. ``eval_tracks`` and
``combo_basket_catalog`` re-export. Flip only with a dated brief.
"""

EVENT_THREE_AND_PLUS_N_STOPPED: bool = True
CATALOG_AND_PLUS_N_STOPPED: bool = True
# Freeze n. yaml n>0 must equal this; yaml n==0 later ok if compiled migration n matches (yaml_still_present may then be false). Does not delete YAML.
CATALOG_YAML_COUNT_AT_STOP: int = 2254
RECONSTITUTION_APPLY: bool = False
CURRENT_EVAL_WAVE: str = "20260824ev"
