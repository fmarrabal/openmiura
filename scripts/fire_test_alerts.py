from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Send synthetic alerts to Alertmanager for end-to-end validation.")
    p.add_argument("--alertmanager-url", default="http://localhost:9093", help="Base URL of Alertmanager")
    p.add_argument("--payload", default="ops/alertmanager/testdata/sample_alerts.json", help="Path to JSON payload")
    p.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout")
    return p


def load_payload(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError("Payload must be a JSON list of alert objects")
    return data


def send_alerts(*, alertmanager_url: str, payload_path: str | Path, timeout: float = 5.0) -> httpx.Response:
    payload = load_payload(payload_path)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(alertmanager_url.rstrip("/") + "/api/v2/alerts", json=payload)
        response.raise_for_status()
        return response


def main() -> int:
    args = build_parser().parse_args()
    response = send_alerts(alertmanager_url=args.alertmanager_url, payload_path=args.payload, timeout=args.timeout)
    print(f"Posted synthetic alerts to {args.alertmanager_url.rstrip('/')}/api/v2/alerts -> {response.status_code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
