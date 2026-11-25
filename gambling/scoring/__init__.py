"""Turn model probabilities into EV, Kelly, tier, authorization and betsheets.

Plan Phase 5/7. The ONLY layer that assigns tier or authorization status; it
reads release authority from the model registry at quote time. Adapters in
``gambling.models`` return probabilities only. Not implemented yet.
"""
