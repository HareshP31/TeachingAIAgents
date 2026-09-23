from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


BASE = "http://localhost:8000"


def request(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def wait_ready() -> None:
    for _ in range(60):
        try:
            if request("GET", "/health/ready")["status"] == "ready":
                return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(1)
    raise SystemExit("backend did not become ready")


def main() -> None:
    wait_ready()
    onboarding = request("POST", "/api/dev/runs", {
        "question": "Which acquisition pathway applies to commercial cloud hosting?",
    })
    assert onboarding["run"]["status"] == "completed"
    assert onboarding["run"]["route"] == "analyst"
    market = request("POST", "/api/dev/runs", {
        "question": "What vendors have recent Space Force contracts under Cloud One?",
    })
    assert market["interrupted"] is True
    assert market["run"]["risk_score"] >= 50
    assert market["run"]["revision_count"] == 1
    completed = request("POST", f"/api/dev/runs/{market['run']['id']}/review", {"approved": True})
    assert completed["run"]["status"] == "completed"
    print("PASS: ingestion-independent RAG route, critic loop, risk gate, review resume")


if __name__ == "__main__":
    main()
