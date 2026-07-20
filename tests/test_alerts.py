import json

from optionsbot.paper.alerts import TelegramAlerter, discover_chat_id


def test_send_posts_to_bot_api():
    calls = {}

    def http(url, data=None, **kw):
        calls["url"], calls["data"] = url, data
        return b'{"ok": true}'

    ok = TelegramAlerter("TOKEN123", "42", http=http).send("kill-switch tripped")
    assert ok
    assert "botTOKEN123/sendMessage" in calls["url"]
    body = calls["data"].decode()
    assert "chat_id=42" in body and "kill-switch+tripped" in body


def test_send_failure_never_raises_and_logs():
    log = []

    def http(url, data=None, **kw):
        raise OSError("network down")

    ok = TelegramAlerter("T", "42", log=log.append, http=http).send("halt reason")
    assert not ok
    assert any("telegram send failed" in m and "halt reason" in m for m in log)


def test_discover_chat_id_takes_latest_message():
    updates = {"result": [
        {"message": {"chat": {"id": 111}}},
        {"message": {"chat": {"id": 222}}},
    ]}
    got = discover_chat_id("T", http=lambda url, data=None, **kw: json.dumps(updates).encode())
    assert got == "222"


def test_discover_chat_id_none_when_no_messages():
    got = discover_chat_id("T", http=lambda url, data=None, **kw: b'{"result": []}')
    assert got is None
