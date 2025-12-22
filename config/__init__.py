# config/__init__.py
from config.settings import REQUIRED_ENV_VARS
import os

missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
if missing:
    raise RuntimeError(f"Missing required env vars: {missing}")
