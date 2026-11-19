"""Run the private gateway with synthetic equipment responses. Isolated tests only.

Mount this script, equipment_provider.py and examples into a dedicated container.
Use only its synthetic key and an internal-only network. Production never imports it.
"""

from equipment_provider import recorded_reply

from awm_adm.gateway import service
from awm_adm.runtime import component
from awm_adm.runtime.protocol import dumps, loads


def transport(provider, wire, credential, timeout):
    if provider != "openai" or credential != "synthetic-test-secret":
        return 401, dumps({"error": {"code": "invalid_api_key"}})
    body = loads(wire)
    if body["text"]["format"]["name"] == "adm_connection_test":
        reply = {"ok": True}
    else:
        reply = recorded_reply(wire)
    return 200, dumps(
        {
            "id": "synthetic-response",
            "model": body["model"],
            "status": "completed",
            "usage": {"input_tokens": 120, "output_tokens": 40},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": dumps(reply).decode()}],
                }
            ],
        }
    )


class FixtureGateway(service.Gateway):
    def __init__(self, store, exchange):
        super().__init__(store, exchange, transport=transport)


if __name__ == "__main__":
    service.Gateway = FixtureGateway
    component.main()
