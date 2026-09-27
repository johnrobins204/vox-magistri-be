# app/config.py
"""
Application configuration loader for the DnD server.

Features:
- Namespaced settings (ollama, app, server, tools, prompts, world, database, auth, logging)
- Typed Pydantic models for safety and autocomplete
- Single settings.json file at project root
- Read-only access (no setters)
- get_settings() returns the full typed Settings object
- get_namespace("ollama") returns a dict for that namespace
- get("ollama.model") returns a single value via dotted path
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict

from pydantic import BaseModel, Field


# ------------------------------------------------------------
# Namespace Models
# ------------------------------------------------------------

class OllamaSettings(BaseModel):
    base_url: str = Field(default="http://127.0.0.1:11434")
    model: str = Field(default="llama3.1:8b")
    timeout_seconds: float = Field(default=30.0)
    stream: bool = Field(default=False)


class AppSettings(BaseModel):
    environment: str = Field(default="development")
    seed_sample_data: bool = Field(default=False)
    max_turns: int = Field(default=6)
    max_field_len: int = Field(default=240)


class ServerSettings(BaseModel):
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=5000)
    allowed_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ])


class ToolSettings(BaseModel):
    enable_discovery: bool = Field(default=True)
    tool_packages: list[str] = Field(default_factory=lambda: ["intelligence.tools"])


class PromptVoiceSettings(BaseModel):
    tone: str = Field(default="neutral")
    persona: str = Field(default="classic_dm")
    sensory_focus: str = Field(default="balanced")
    consequence_level: str = Field(default="moderate")


class PromptSettings(BaseModel):
    enable_narration: bool = Field(default=True)
    enable_adjudication: bool = Field(default=True)
    verbosity_default: str = Field(default="normal")
    dm_voice: PromptVoiceSettings = Field(default_factory=PromptVoiceSettings)


class WorldSettings(BaseModel):
    enable_world_guidance: bool = Field(default=True)
    default_modes: list[str] = Field(default_factory=lambda: ["Clarify", "Expand", "Connect", "Challenge"])


class DatabaseSettings(BaseModel):
    url: str = Field(default="sqlite:///./dnd.db")
    echo: bool = Field(default=False)


class AuthSettings(BaseModel):
    local_dev_token: str = Field(default="dev")
    enable_auth: bool = Field(default=True)


class LoggingSettings(BaseModel):
    level: str = Field(default="INFO")
    log_dir: str = Field(default="logs")


# ------------------------------------------------------------
# Root Settings Model
# ------------------------------------------------------------

class Settings(BaseModel):
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    app: AppSettings = Field(default_factory=AppSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    tools: ToolSettings = Field(default_factory=ToolSettings)
    prompts: PromptSettings = Field(default_factory=PromptSettings)
    world: WorldSettings = Field(default_factory=WorldSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


# ------------------------------------------------------------
# File Loader
# ------------------------------------------------------------

def _load_json(path: str) -> dict:
    """Load JSON file if present; return {} if missing or invalid."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


# ------------------------------------------------------------
# Settings Accessors
# ------------------------------------------------------------

@lru_cache()
def get_settings() -> Settings:
    """
    Load settings.json once and cache it.
    Environment variables override JSON values.
    """
    data = _load_json("settings.json")

    # Environment overrides (flat or nested)
    env_overrides = {}

    for key, value in os.environ.items():
        if "__" in key:
            # Nested override: e.g., OLLAMA__MODEL
            ns, field = key.split("__", 1)
            ns = ns.lower()
            field = field.lower()
            env_overrides.setdefault(ns, {})[field] = value
        else:
            # Flat override (rare)
            env_overrides[key.lower()] = value

    # Merge JSON + env overrides
    merged = {**data}

    for ns, fields in env_overrides.items():
        if isinstance(fields, dict):
            merged.setdefault(ns, {})
            merged[ns].update(fields)
        else:
            merged[ns] = fields

    return Settings(**merged)


def get_namespace(name: str) -> Dict[str, Any]:
    """
    Return a namespace as a plain dictionary.
    Example: get_namespace("ollama")
    """
    settings = get_settings()
    ns = getattr(settings, name, None)
    if ns is None:
        raise KeyError(f"Namespace '{name}' not found")
    return ns.dict()


def get(path: str) -> Any:
    """
    Return a single setting via dotted path.
    Example: get("ollama.model")
    """
    settings = get_settings()
    parts = path.split(".")
    obj = settings
    for part in parts:
        obj = getattr(obj, part, None)
        if obj is None:
            raise KeyError(f"Setting '{path}' not found")
    return obj
