import requests

from common.alerts import Alert, send_alert, to_discord_payload


class FakeResponse:
    def __init__(self, status_code=204):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.posts = response or FakeResponse(), error, []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        if self.error:
            raise self.error
        return self.response


def make_alert(**overrides):
    values = dict(severity="critical", title="daily_pipeline failed at fx", pipeline="daily_pipeline",
                  env="prod", run_id="prod-1", message="Timeout", step="fx", hint="Check the API")
    values.update(overrides)
    return Alert(**values)


def test_payload_has_colour_step_and_hint():
    embed = to_discord_payload(make_alert())["embeds"][0]
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert embed["color"] == 0xD7263D
    assert "CRITICAL" in embed["title"]
    assert fields["Step"] == "fx" and fields["What to check"] == "Check the API"


def test_long_messages_are_clipped_to_discord_limits():
    embed = to_discord_payload(make_alert(message="x" * 10_000))["embeds"][0]
    assert len(embed["description"]) <= 4096


def test_not_sent_when_disabled_or_no_webhook():
    session = FakeSession()
    assert send_alert(make_alert(), "https://hook", enabled=False, session=session) is False
    assert send_alert(make_alert(), None, enabled=True, session=session) is False
    assert session.posts == []


def test_sent_when_enabled():
    session = FakeSession()
    assert send_alert(make_alert(), "https://hook", enabled=True, session=session) is True
    assert session.posts[0][0] == "https://hook"


def test_delivery_failure_does_not_raise():
    session = FakeSession(error=requests.ConnectionError("down"))
    assert send_alert(make_alert(), "https://hook", enabled=True, session=session) is False
