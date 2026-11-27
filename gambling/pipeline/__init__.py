"""Daily pipelines: capture -> frozen scorer -> complete bet sheet, with a hashed run manifest.

Status: UNVALIDATED_GENERALIZED_WRAPPER. A daily pipeline wraps a frozen, date-specific release scorer
unchanged. It is not a validated generalized live pipeline until its dual-run period (ROADMAP M3) and
an independent validation decision (M4). The frozen scorer and its release authority are what decide
each row; the wrapper only supplies inputs and records what happened.
"""
