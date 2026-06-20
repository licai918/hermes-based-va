"""Toee Tire Hermes VA plugin package.

The Python Hermes-integration layer per ADR-0139: Domain Adapter Tools, the Tool
Gate, and governed dispatch. Only this layer (and the gateway embedding) may
import ``hermes_agent`` / ``run_agent``; ``apps/workbench`` calls the Hermes API
Server over HTTP instead.
"""
