"""Test-only dummy strategies for the core engine.

These exist to exercise the engine end-to-end without a real strategy
implementation (those live under top-level ``strategies/`` in a later phase).
They implement :class:`core.strategy_protocol.Strategy` and expose
``strategy_id`` / ``params`` so their identity is captured in result metadata.
"""
