"""Où tourne ce Core : les outils PC (Windows, ctypes) ne se chargent que sur le PC principal.

Core sur le mini-PC (Linux) : `HAS_PC_TOOLS` est faux, les outils PC viendront de l'agent PC (docs/MIGRATION_CORE_MINIPC.md,
lot 3). `JARVIS_PC_TOOLS=0` force le même mode sous Windows (essais).
"""
import os
import sys

HAS_PC_TOOLS = sys.platform == "win32" and os.environ.get("JARVIS_PC_TOOLS") != "0"
