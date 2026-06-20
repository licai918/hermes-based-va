"""Hermes Runtime Shim (ADR-0139, ADR-0100).

This is the only Python layer that imports the upstream Nous ``hermes-agent``
(`hermes_agent` / `run_agent` / `hermes_cli`). It boots a Hermes profile with the
``toee_hermes`` plugin registered, so the gateway embedding and the launch-eval
live harness share one SDK-pinned entry point. The launch-eval runner in
``../hermes`` stays dependency-free and never imports the SDK directly.
"""
