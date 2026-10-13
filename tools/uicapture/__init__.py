"""Offline capture of the router web UI's own API requests.

The router's UI pages (anonymised fixtures) and UI scripts run in a headless
browser against a local mock router; every API request the UI code builds is
recorded. Those recordings ("goldens") are the reference the client's request
bodies are tested against. Nothing here can reach the real router: see
:mod:`tools.uicapture.guard`.
"""
