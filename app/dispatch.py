"""
dispatch.py — V6.0 Email + Telegram delivery for high-conviction decisions
============================================================================

The Lewis suite's Ross, adapted to STP. Fires email (always, if configured) and
Telegram (optional) when STP produces ACT_NOW + HIGH conviction decisions that
have not already been dispatched.

Idempotent. Each decision can be dispatched once. The journal records every
dispatch attempt. NEVER places trades — that's the executor's job.

Environment (in .env):
  GMAIL_USER             — sending Gmail address
  GMAIL_APP_PASSWORD     — 16-char app password from myaccount.google.com/apppasswords
  GMAIL_TO               — recipient address (defaults to GMAIL_USER if blank)
  TELEGRAM_BOT_TOKEN     — optional bot token from @BotFather
  TELEGRAM_CHAT_ID       — optional chat id; the bot must have messaged this chat once

Wire-in: in platform.py scan_signals(), after decisions are built and
auto-execute runs:

    from app.dispatch import dispatch_pending_decisions
    dispatch_pending_decisions(self.state)
"""
from __future__ import annotations

import os
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, List, Set


# Decisions are eligible for dispatch when they meet these criteria.
DISPATCH_URGENCY_TIERS = {"ACT_NOW", "TODAY"}
DISPATCH_CONVICTION_TIERS = {"HIGH", "MEDIUM"}

# Maximum dispatches per scan to prevent runaway alerts on busy days.
MAX_DISPATCHES_PER_SCAN = 5


def _dispatched_decision_ids(state: Dict[str, Any]) -> Set[str]:
    """Pull the set of decision IDs we've already dispatched, from the journal."""
    seen: Set[str] = set()
    for entry in state.get("journal", []) or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("event") == "decision_dispatched":
            did = entry.get("decision_id")
            if did:
                seen.add(str(did))
    return seen


def _build_subject(decision: Dict[str, Any]) -> str:
    action = decision.get("action", "DECISION")
    symbol = decision.get("symbol", "?")
    conviction = decision.get("conviction", "")
    urgency = decision.get("urgency", "")
    return f"[STP] {urgency} · {conviction} · {action} {symbol}"


def _build_body(decision: Dict[str, Any]) -> str:
    """Plain-text body — same for email and Telegram."""
    lines = []
    lines.append(decision.get("one_line", "")[:200])
    lines.append("")
    lines.append("─" * 60)
    lines.append(f"Symbol:     {decision.get('symbol', '?')}")
    lines.append(f"Action:     {decision.get('action', '?')}")
    lines.append(f"Conviction: {decision.get('conviction', '?')}")
    lines.append(f"Urgency:    {decision.get('urgency', '?')}")
    lines.append(f"Driver:     {decision.get('primary_driver', '?')}")

    if decision.get("constellation_pattern"):
        lines.append(
            f"Pattern:    {decision['constellation_pattern']} "
            f"[{decision.get('constellation_stage', '')}]"
        )

    plan = decision.get("plan", {}) or {}
    if plan:
        lines.append("")
        lines.append("Plan:")
        lines.append(f"  Entry:    ${plan.get('entry_price', 0):.4f}")
        lines.append(f"  Stop:     ${plan.get('stop_price', 0):.4f} ({plan.get('stop_pct_from_entry', 0):.1f}%)")
        lines.append(f"  Target:   ${plan.get('first_target', 0):.4f} ({plan.get('target_pct_from_entry', 0):.1f}%)")
        lines.append(f"  R:R:      {plan.get('risk_reward_ratio', 0):.2f}")
        lines.append(f"  Time:     {plan.get('time_stop_days', 0)}d")

    sizing = decision.get("sizing", {}) or {}
    if sizing:
        lines.append("")
        lines.append("Sizing:")
        lines.append(
            f"  ${sizing.get('suggested_dollars', 0):,.0f} "
            f"({sizing.get('suggested_quantity', 0)} units, "
            f"{sizing.get('pct_of_equity', 0):.1f}% of equity)"
        )
        lines.append(f"  VIX mult: {sizing.get('vix_multiplier', 1.0):.2f}x")

    why = decision.get("why", "")
    if why:
        lines.append("")
        lines.append(f"Why: {why}")

    kc = decision.get("kill_conditions", []) or []
    if kc:
        lines.append("")
        lines.append("Kill conditions:")
        for c in kc:
            lines.append(f"  · {c}")

    lines.append("")
    lines.append("─" * 60)
    lines.append("STP did not place a trade. The decision is yours.")
    return "\n".join(lines)


def _send_email(subject: str, body: str) -> tuple[bool, str]:
    user = os.environ.get("GMAIL_USER", "").strip()
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").strip().replace(" ", "")
    to = os.environ.get("GMAIL_TO", "").strip() or user
    if not user or not pw:
        return False, "GMAIL_USER / GMAIL_APP_PASSWORD not configured"
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to
        msg.set_content(body)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
            s.login(user, pw)
            s.send_message(msg)
        return True, "ok"
    except Exception as exc:
        return False, f"email error: {exc}"


def _send_telegram(subject: str, body: str) -> tuple[bool, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return False, "telegram not configured"
    try:
        text = f"*{subject}*\n\n```\n{body}\n```"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat, "text": text, "parse_mode": "Markdown",
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return (200 <= resp.status < 300, f"http {resp.status}")
    except Exception as exc:
        return False, f"telegram error: {exc}"


def dispatch_pending_decisions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Send email/Telegram for every undispatched eligible decision in state.

    Returns a list of result dicts, each describing what happened. The journal
    is updated in-place so dispatches are idempotent across scan cycles.
    """
    decisions = state.get("decisions", []) or []
    if not decisions:
        return []

    already_dispatched = _dispatched_decision_ids(state)
    results: List[Dict[str, Any]] = []
    fired = 0

    for d in decisions:
        if fired >= MAX_DISPATCHES_PER_SCAN:
            break
        if not isinstance(d, dict):
            continue
        did = str(d.get("id", ""))
        if not did or did in already_dispatched:
            continue
        urgency = str(d.get("urgency", ""))
        conviction = str(d.get("conviction", ""))
        if urgency not in DISPATCH_URGENCY_TIERS:
            continue
        if conviction not in DISPATCH_CONVICTION_TIERS:
            continue

        subject = _build_subject(d)
        body = _build_body(d)

        email_ok, email_note = _send_email(subject, body)
        tg_ok, tg_note = _send_telegram(subject, body)

        result = {
            "decision_id": did,
            "symbol": d.get("symbol"),
            "action": d.get("action"),
            "email_sent": email_ok,
            "email_note": email_note,
            "telegram_sent": tg_ok,
            "telegram_note": tg_note,
        }
        results.append(result)
        fired += 1

        # Idempotency record. If email failed we DON'T mark dispatched so a
        # subsequent scan can retry. If at least one channel succeeded, mark it
        # so we don't double-fire.
        if email_ok or tg_ok:
            state.setdefault("journal", []).append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "decision_dispatched",
                "decision_id": did,
                "symbol": d.get("symbol"),
                "channels": {"email": email_ok, "telegram": tg_ok},
            })

    return results


def dispatch_status() -> Dict[str, Any]:
    """Quick check whether dispatch is configured. For the UI's Settings panel."""
    return {
        "email_configured": bool(os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD")),
        "telegram_configured": bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")),
    }
