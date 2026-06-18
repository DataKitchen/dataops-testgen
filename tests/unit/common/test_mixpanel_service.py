import queue
from unittest.mock import MagicMock

import pytest

from testgen import settings
from testgen.common import mixpanel_service as mp_module
from testgen.common.mixpanel_service import MixpanelService
from testgen.utils.singleton import SingletonType


@pytest.fixture
def service(monkeypatch):
    """Fresh, isolated MixpanelService with analytics on and no real network/DB."""
    SingletonType._instances.pop(MixpanelService, None)
    monkeypatch.setattr(settings, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(settings, "MIXPANEL_TOKEN", "tok")
    # Avoid Streamlit + DB: session.auth falsy, instance_id pre-seeded.
    monkeypatch.setattr(mp_module, "session", MagicMock(auth=None))
    svc = MixpanelService()
    svc.__dict__["instance_id"] = "iid"
    yield svc
    svc.drain()
    SingletonType._instances.pop(MixpanelService, None)


def test_send_event_enqueues_and_worker_flushes_one_event(service, monkeypatch):
    captured = []
    monkeypatch.setattr(service, "send_mp_request", lambda endpoint, payload: captured.append((endpoint, payload)))

    service.send_event("nav-home")
    service.drain()

    assert len(captured) == 1
    endpoint, payload = captured[0]
    assert endpoint == "track?ip=1"
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["event"] == "nav-home"
    assert payload[0]["properties"]["token"] == "tok"  # noqa: S105 (test token, not a secret)
    assert payload[0]["properties"]["instance_id"] == "iid"
    assert "time" in payload[0]["properties"]


def test_next_batch_caps_at_batch_size(service, monkeypatch):
    monkeypatch.setattr(mp_module, "_BATCH_SIZE", 2)
    service._queue = queue.Queue()
    for i in range(5):
        service._queue.put({"event": f"e{i}", "properties": {}})

    batch, stop = service._next_batch()

    assert [e["event"] for e in batch] == ["e0", "e1"]
    assert stop is False


def test_next_batch_stops_on_sentinel_and_returns_pending(service):
    service._queue = queue.Queue()
    service._queue.put({"event": "a", "properties": {}})
    service._queue.put({"event": "b", "properties": {}})
    service._queue.put(mp_module._SHUTDOWN)

    batch, stop = service._next_batch()

    assert [e["event"] for e in batch] == ["a", "b"]
    assert stop is True


def test_flush_chunks_over_batch_size(service, monkeypatch):
    monkeypatch.setattr(mp_module, "_BATCH_SIZE", 2)
    posts = []
    monkeypatch.setattr(service, "send_mp_request", lambda _endpoint, payload: posts.append(len(payload)))

    service._flush([{"event": f"e{i}", "properties": {}} for i in range(3)])

    assert posts == [2, 1]


def test_queue_overflow_drops_and_warns(service, monkeypatch, caplog):
    # Pretend the worker is running so _enqueue does not start a real one,
    # and give it a size-1 queue that nothing drains.
    service._started = True
    service._queue = queue.Queue(maxsize=1)

    service._enqueue({"event": "a", "properties": {}})
    with caplog.at_level("WARNING"):
        service._enqueue({"event": "b", "properties": {}})

    assert service._queue.qsize() == 1
    assert "analytics queue full" in caplog.text


def test_drain_stops_worker_and_is_idempotent(service, monkeypatch):
    monkeypatch.setattr(service, "send_mp_request", lambda *_: None)
    service.send_event("x")  # starts worker

    service.drain()
    assert service._worker is not None
    assert not service._worker.is_alive()

    service.drain()  # second call is a no-op, must not raise


def test_analytics_disabled_never_starts_worker(service, monkeypatch):
    monkeypatch.setattr(settings, "ANALYTICS_ENABLED", False)
    posts = []
    monkeypatch.setattr(service, "send_mp_request", lambda _endpoint, payload: posts.append(payload))

    service.send_event("nav-home")
    service.drain()

    assert service._started is False
    assert service._worker is None
    assert posts == []


def test_send_event_after_drain_drops_and_warns(service, monkeypatch, caplog):
    posts = []
    monkeypatch.setattr(service, "send_mp_request", lambda _endpoint, payload: posts.append(payload))

    service.send_event("pre-drain")
    service.drain()

    posts.clear()
    with caplog.at_level("WARNING"):
        service.send_event("late")

    assert "stopped" in caplog.text
    assert posts == []


def test_send_feedback_posts_synchronously_without_worker(service, monkeypatch):
    posts = []
    monkeypatch.setattr(service, "send_mp_request", lambda endpoint, payload: posts.append((endpoint, payload)))

    service.send_feedback(comment="great tool")

    # Posted immediately (no drain needed), as a single dict (not a list), worker never started.
    assert len(posts) == 1
    endpoint, payload = posts[0]
    assert endpoint == "track?ip=1"
    assert isinstance(payload, dict)
    assert payload["event"] == "feedback"
    assert payload["properties"]["comment"] == "great tool"
    assert service._started is False
    assert service._worker is None
