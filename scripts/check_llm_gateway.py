"""Safe connectivity check for the organizer supplied LLM Gateway."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dell_agent.agent.loop import GatewayClient, GatewayRequestError


def main() -> int:
    url = os.getenv("LLM_GATEWAY_URL", "").strip()
    api_key = os.getenv("LLM_GATEWAY_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    missing = [
        name for name, value in (
            ("LLM_GATEWAY_URL", url),
            ("LLM_GATEWAY_API_KEY", api_key),
            ("LLM_MODEL", model),
        ) if not value
    ]
    if missing:
        print("Missing configuration: " + ", ".join(missing), file=sys.stderr)
        return 2
    client = GatewayClient(url, api_key, model)
    try:
        response = client.chat(
            [{"role": "user", "content": "Reply with exactly: gateway-ok"}],
            [],
        )
    except GatewayRequestError as exc:
        print(f"Gateway check failed: {exc}", file=sys.stderr)
        return 1
    content = response["message"]["content"].strip()
    print(f"Gateway reachable: protocol={client.protocol}, model={model}, response_received={bool(content)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
