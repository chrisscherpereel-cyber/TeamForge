"""Shared test fixtures/config.

Sets a throwaway Fernet key + local vault backend BEFORE any teamformation
module imports config, so the encrypted local vault works in-process.
"""
import os
import sys

from cryptography.fernet import Fernet

# Ensure the package is importable when pytest is run from the repo root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("VAULT_BACKEND", "local")
