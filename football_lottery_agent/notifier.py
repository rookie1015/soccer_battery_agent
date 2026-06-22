from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


class NotifyError(RuntimeError):
    pass


@dataclass(frozen=True)
class NotifyResult:
    channel: str
    response_text: str


def send_report(channel: str, report_path: str | Path, webhook_url: str | None = None) -> NotifyResult:
    normalized = channel.lower()
    report_text = Path(report_path).read_text(encoding="utf-8")
    url = webhook_url or _webhook_from_env(normalized)

    if normalized == "feishu":
        payload = _feishu_payload(report_text)
    elif normalized in {"wechat", "wecom"}:
        payload = _wecom_payload(report_text)
    else:
        raise NotifyError("Unsupported channel. Use 'feishu' or 'wechat'.")

    response_text = _post_json(url, payload)
    return NotifyResult(channel=normalized, response_text=response_text)


def _webhook_from_env(channel: str) -> str:
    env_name = "FEISHU_WEBHOOK_URL" if channel == "feishu" else "WECOM_WEBHOOK_URL"
    value = os.getenv(env_name)
    if not value:
        raise NotifyError(f"Missing webhook URL. Set {env_name} or pass --webhook-url.")
    return value


def _feishu_payload(report_text: str) -> dict[str, object]:
    return {
        "msg_type": "text",
        "content": {
            "text": _trim_for_message(report_text),
        },
    }


def _wecom_payload(report_text: str) -> dict[str, object]:
    return {
        "msgtype": "markdown",
        "markdown": {
            "content": _trim_for_message(report_text),
        },
    }


def _post_json(url: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise NotifyError(f"Failed to send notification: {exc}") from exc


def _trim_for_message(text: str, limit: int = 3500) -> str:
    if len(text) <= limit:
        return text
    suffix = "\n\n......\n报告过长，已截断。请打开本地 Markdown 查看完整内容。"
    return text[: limit - len(suffix)] + suffix
