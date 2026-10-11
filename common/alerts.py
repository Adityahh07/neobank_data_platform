"""Send pipeline alerts to Discord (docs/requirements.md §11).

Every alert is printed to the console. It is also posted to Discord when alerts
are enabled and a webhook URL is configured. A failure to deliver an alert is
reported but never crashes the pipeline - the original error matters more.
"""

from dataclasses import dataclass, field

import requests

# Discord embed colours and title markers per severity
SEVERITIES = {
    "critical": (0xD7263D, "\U0001F534 CRITICAL"),
    "warning": (0xF4A100, "\U0001F7E0 WARNING"),
    "info": (0x2E9E5B, "\U0001F7E2 INFO"),
}

# Discord limits: embed description 4096 chars, field value 1024 chars
MAX_DESCRIPTION = 4000
MAX_FIELD = 1000


@dataclass
class Alert:
    severity: str
    title: str
    pipeline: str
    env: str
    run_id: str
    message: str = ""
    step: str | None = None
    hint: str | None = None
    details: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if self.severity not in SEVERITIES:
            raise ValueError(f"Unknown severity {self.severity!r}")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def to_discord_payload(alert: Alert) -> dict:
    colour, marker = SEVERITIES[alert.severity]
    fields = [
        {"name": "Pipeline", "value": alert.pipeline, "inline": True},
        {"name": "Environment", "value": alert.env, "inline": True},
        {"name": "Run ID", "value": alert.run_id, "inline": False},
    ]
    if alert.step:
        fields.insert(2, {"name": "Step", "value": alert.step, "inline": True})
    for name, value in alert.details.items():
        fields.append({"name": name, "value": _clip(str(value), MAX_FIELD), "inline": True})
    if alert.hint:
        fields.append({"name": "What to check", "value": _clip(alert.hint, MAX_FIELD), "inline": False})
    return {
        "username": "Neobank Data Platform",
        "embeds": [{
            "title": f"{marker}: {alert.title}",
            "description": _clip(alert.message, MAX_DESCRIPTION),
            "color": colour,
            "fields": fields,
        }],
    }


def send_alert(alert: Alert, webhook_url: str | None, enabled: bool,
               session: requests.Session | None = None) -> bool:
    """Print the alert and post it to Discord if enabled. Returns True if delivered."""
    print(f"[{alert.severity.upper()}] {alert.title} ({alert.pipeline}/{alert.env}, run {alert.run_id})")
    if alert.message:
        print(f"    {alert.message}")
    if not enabled:
        print("    (alerts disabled for this run - not sent to Discord)")
        return False
    if not webhook_url:
        print("    (DISCORD_WEBHOOK_URL not set - not sent to Discord)")
        return False
    try:
        response = (session or requests).post(webhook_url, json=to_discord_payload(alert), timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"    WARNING: could not deliver alert to Discord: {exc}")
        return False
