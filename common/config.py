"""Project paths and settings per environment (docs/architecture.md §7).

Secrets such as the Discord webhook URL are read from environment variables,
loaded from a git-ignored `.env` file in the project root (see `.env.example`).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

PAYSIM_SOURCES = {
    "dev": ROOT / "data/landing/paysim_sample/paysim_day1.csv",
    "prod": ROOT / "data/landing/paysim/PS_20174392719_1491204439457_log.csv",
}


@dataclass(frozen=True)
class EnvConfig:
    name: str
    lake: Path
    warehouse: Path
    paysim_source: Path


def env_config(env: str) -> EnvConfig:
    if env not in PAYSIM_SOURCES:
        raise ValueError(f"Unknown environment {env!r}; expected one of {sorted(PAYSIM_SOURCES)}")
    data = ROOT / "data" / env
    return EnvConfig(env, data / "lake", data / "neobank.duckdb", PAYSIM_SOURCES[env])


def discord_webhook_url() -> str | None:
    return os.getenv("DISCORD_WEBHOOK_URL") or None
