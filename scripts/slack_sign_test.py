from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import uuid

import httpx


def slack_signature(signing_secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def make_url_verification_payload(challenge: str) -> dict:
    return {"type": "url_verification", "challenge": challenge}


def make_event_callback_payload(
    *,
    team_id: str,
    event_type: str,
    channel: str,
    user: str,
    text: str,
    channel_type: str | None = "im",
    bot_user_id: str = "",
) -> dict:
    event_id = f"Ev{uuid.uuid4().hex[:16]}"
    ts = str(time.time())

    if event_type == "app_mention" and bot_user_id:
        text = f"<@{bot_user_id}> {text}"

    event = {
        "type": event_type,
        "user": user,
        "text": text,
        "channel": channel,
        "ts": ts,
    }
    if channel_type:
        event["channel_type"] = channel_type

    return {
        "type": "event_callback",
        "team_id": team_id,
        "api_app_id": "A_TEST",
        "event": event,
        "event_id": event_id,
        "event_time": int(time.time()),
    }


def post(url: str, secret: str, payload: dict):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time()))
    sig = slack_signature(secret, ts, body)

    headers = {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
    }

    with httpx.Client(timeout=20) as client:
        r = client.post(url, content=body, headers=headers)

    return r.status_code, r.text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8081/slack/events")
    ap.add_argument("--secret", required=True)
    ap.add_argument("--mode", choices=["url_verification", "event_callback"], default="url_verification")
    ap.add_argument("--repeat", type=int, default=1)

    ap.add_argument("--challenge", default="abc123")

    ap.add_argument("--team-id", default="T_TEST")
    ap.add_argument("--event-type", choices=["app_mention", "message"], default="app_mention")
    ap.add_argument("--channel", default="C_TEST")
    ap.add_argument("--user", default="U_TEST")
    ap.add_argument("--text", default="hola desde slack_sign_test")
    ap.add_argument("--channel-type", default="im")
    ap.add_argument("--bot-user-id", default="")

    args = ap.parse_args()

    if args.mode == "url_verification":
        payload = make_url_verification_payload(args.challenge)
        code, txt = post(args.url, args.secret, payload)
        print("STATUS:", code)
        print("RESPONSE:", txt)
        return

    # event callback
    payload = make_event_callback_payload(
        team_id=args.team_id,
        event_type=args.event_type,
        channel=args.channel,
        user=args.user,
        text=args.text,
        channel_type=args.channel_type,
        bot_user_id=args.bot_user_id,
    )

    for i in range(args.repeat):
        code, txt = post(args.url, args.secret, payload)
        print(f"[{i+1}/{args.repeat}] STATUS:", code, "RESPONSE:", txt)


if __name__ == "__main__":
    main()