"""
Reset the sandbox demo to its seed data now, instead of waiting for the next scheduled reset.

Runs inside the server's machine and asks the running API to do the reset, because the
embedded Qdrant index is single-process: a second process can't open it while the
server holds it. Needs DEMO__RESET_TOKEN set (as a Fly secret, it is already in the
machine's environment):

    fly ssh console -C "python scripts/reset_demo.py"

The reset also rebuilds the semantic-search index, so on a demo deployment it replaces
scripts/reindex_listings.py.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

URL = os.environ.get("DEMO_RESET_URL", "http://127.0.0.1:8000/api/v1/demo/reset")


def main() -> int:
    token = os.environ.get("DEMO__RESET_TOKEN", "")
    if not token:
        print("DEMO__RESET_TOKEN is not set", file=sys.stderr)
        return 1
    request = urllib.request.Request(  # noqa: S310 - fixed local URL
        URL, method="POST", headers={"X-Demo-Reset-Token": token}
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        body = json.loads(response.read())
    print(f"Demo reset done. Next scheduled reset: {body['next_reset_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
