"""Configuration loader for ClaimFlow AI."""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """
    Load configuration from YAML file and environment variables.

    Args:
        config_path: Path to settings.yaml. If None, uses default location.

    Returns:
        Merged configuration dictionary
    """
    # Load .env file
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / ".env"
    load_dotenv(env_path)

    # Load YAML config
    if config_path is None:
        config_path = project_root / "config" / "settings.yaml"

    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    # Inject environment variables
    config["gemini_api_key"] = os.getenv("GEMINI_API_KEY", "")
    config["gemini_model"] = os.getenv("GEMINI_MODEL", config.get("llm", {}).get("default_model", "gemini-2.5-flash"))
    config["yahoo_email"] = os.getenv("YAHOO_EMAIL", "")
    config["yahoo_app_password"] = os.getenv("YAHOO_APP_PASSWORD", "")
    config["log_level"] = os.getenv("LOG_LEVEL", "INFO")

    return config


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent
