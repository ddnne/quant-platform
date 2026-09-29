"""Live research control flags. Not scores. Not GO.

Current ExperimentPlan checks consume these stop/apply flags.
The historical catalog and its reconstitution tooling are retired.
"""

EVENT_THREE_AND_PLUS_N_STOPPED: bool = True
CATALOG_AND_PLUS_N_STOPPED: bool = True
RECONSTITUTION_APPLY: bool = False
