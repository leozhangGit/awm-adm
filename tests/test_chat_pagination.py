"""History windows are read-only; storage, context and legacy cursor direction survive."""

import pytest

from awm_adm.runtime.protocol import dumps

from .test_application import app_runtime as app_runtime
from .test_application import client
from .test_direct_ask import recorded, work
from .test_learning_service import rig as rig


@pytest.mark.parametrize("channel", ["ask", "teach"])
def test_latest_and_older_pages_are_complete_stable_and_channel_scoped(rig, channel):
    rt, gateway = rig
    recorded(rt, gateway, {})
    key = rt.create("Paged history")["id"]
    other_channel = "teach" if channel == "ask" else "ask"
    expected = []
    for n in range(205):
        expected.append(rt.interactions.submit(key, channel, {"text": f"Saved message {n}"})["id"])
        if n % 50 == 0:
            rt.interactions.submit(key, other_channel, {"text": "Separate stream"})
    other = rt.create("Other model")["id"]
    rt.interactions.submit(other, channel, {"text": "Private to the other model"})
    with client(rt) as http:
        url = f"/api/v1/adms/{key}/chat/{channel}"
        latest = http.get(url, params={"direction": "backward", "limit": 100}).json()
        assert [i["id"] for i in latest["items"]] == expected[-100:]
        assert latest["has_more"]
        assert latest["next_cursor"] == latest["items"][0]["sequence"]
        new = rt.interactions.submit(key, channel, {"text": "Arrived while reading"})
        older = http.get(
            url, params={"direction": "backward", "before": latest["next_cursor"], "limit": 100}
        ).json()
        assert [i["id"] for i in older["items"]] == expected[5:105]
        assert older["has_more"]
        first = http.get(
            url, params={"direction": "backward", "before": older["next_cursor"], "limit": 100}
        ).json()
        assert [i["id"] for i in first["items"]] == expected[:5]
        assert not first["has_more"]
        empty = http.get(
            url, params={"direction": "backward", "before": first["next_cursor"], "limit": 100}
        ).json()
        assert not empty["items"] and not empty["has_more"]
        forward = http.get(url, params={"after": latest["items"][-1]["sequence"], "limit": 100}).json()
        assert [i["id"] for i in forward["items"]] == [new["id"]]
        legacy = http.get(url).json()
        assert [i["id"] for i in legacy["items"]] == expected[:20]
        assert http.get(url, params={"before": 3}).status_code == 422
        assert http.get(url, params={"direction": "backward", "after": 1}).status_code == 422
        assert http.get(url, params={"limit": 101}).status_code == 422
    assert rt.learning.usage()["calls"] == 0
    assert len(rt.interactions.chat(key, channel, limit=1000)["items"]) == 206


def test_hidden_previous_exchange_remains_a_valid_followup_and_empty_page_is_explicit(rig):
    rt, gateway = rig
    recorded(rt, gateway, {})
    key = rt.create("Context remains independent")["id"]
    page = rt.interactions.chat(key, "ask", direction="backward", limit=100)
    assert page == {"items": [], "next_cursor": 0, "has_more": False}
    prior = rt.interactions.submit(key, "ask", {"text": "The scenario has two available items."})
    body = work(rt, key, prior["id"])
    body["status"] = "completed"
    with rt.store.db(key) as db:
        db.execute("UPDATE chat_work SET status='completed',body=? WHERE id=?", (dumps(body), prior["id"]))
    for n in range(101):
        rt.interactions.submit(key, "ask", {"text": f"Unrelated API question {n}"})
    assert prior["id"] not in [
        i["id"] for i in rt.interactions.chat(key, "ask", direction="backward", limit=100)["items"]
    ]
    followup = rt.interactions.submit(
        key, "ask", {"text": "And if there are three?", "reply_to": prior["id"]}
    )
    selected = work(rt, key, followup["id"])["selected_context"]
    assert [i["text"] for i in selected] == [prior["text"]]
    assert rt.learning.usage()["calls"] == 0
