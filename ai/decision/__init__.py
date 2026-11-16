"""Laya-based fast decision layer (bot opponent decisions, prompt-injection screening, small plan choices).

Laya (https://pypi.org/project/laya/) is a non-autoregressive decision model: it does not generate text, it answers
typed questions (choice / score / noul) about a short state with calibrated probabilities in one forward pass.
The model is loaded once when the gateway starts (see laya_service.LayaService) and kept in memory.
"""
