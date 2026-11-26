"""Reconcile recorded history against the frozen-replay adapters.

Each sport module rebuilds a scorer's inputs from the rolling database (quotes and events as
they were captured), runs the frozen adapter and compares every recorded ``model_scores`` row
with the replayed one. Read-only: nothing is written to the database.
"""
