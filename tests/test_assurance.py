"""Removed financial controls cannot create authority; retained reads use local access."""

from .test_application import app_runtime as app_runtime
from .test_application import client


def test_financial_mutations_are_retired_and_historical_reads_are_call_free(app_runtime):
    rt = app_runtime
    with client(rt) as http:
        for method, path in (
            ("PUT", "/spending"),
            ("POST", "/prices"),
            ("POST", "/allowances"),
            ("POST", "/connections"),
            ("PUT", "/learning"),
        ):
            assert http.request(method, "/api/v1" + path, json={}).status_code in (404, 405)
        for path in ("/prices", "/allowances"):
            assert http.get("/api/v1" + path).json()["items"] == []
        assert http.get("/api/v1/connection").status_code == 200
        assert http.get("/api/v1/connection", headers={"Origin": "null"}).status_code == 403
    assert rt.learning.usage()["calls"] == 0
