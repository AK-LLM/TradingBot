from __future__ import annotations
import html
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from app.platform import TradingPlatform


def badge(score: float) -> str:
    if score >= 75:
        return "🦈 SHARK"
    if score >= 55:
        return "👀 WATCH"
    return "⚪ LOW"


def flash_banner(p: TradingPlatform) -> None:
    flashes = p.flash_alerts_df()
    if flashes.empty:
        return
    active = flashes[flashes["acknowledged"] != True].sort_values("created_at", ascending=False)  # noqa: E712
    if active.empty:
        return
    top = active.iloc[0]
    reasons = top.reasons if isinstance(top.reasons, list) else []
    action = str(top.action).replace("_", " ")
    components.html(
        f"""
        <div style="position: sticky; top: 0; z-index: 9999; padding: 18px; border-radius: 14px;
                    border: 3px solid #ff3b30; background: linear-gradient(90deg,#3b0000,#8b0000,#3b0000);
                    color: white; font-family: sans-serif; box-shadow: 0 0 24px rgba(255,0,0,.55);">
          <div style="font-size: 26px; font-weight: 800; animation: pulse 1s infinite;">🚨 FLASH ALERT — {html.escape(str(top.narrative))}</div>
          <div style="font-size: 18px; margin-top: 6px;">Action: <b>{html.escape(action)}</b> · Symbol: <b>{html.escape(str(top.primary_symbol))}</b> · Confidence: <b>{float(top.confidence):.1f}</b> · Stage: <b>{html.escape(str(top.trend_stage))}</b></div>
          <div style="font-size: 14px; margin-top: 8px;">{html.escape(' | '.join(map(str, reasons[:4])))}</div>
        </div>
        <style>@keyframes pulse {{ 0% {{opacity:1}} 50% {{opacity:.55}} 100% {{opacity:1}} }}</style>
        <script>
          try {{
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain); gain.connect(ctx.destination); osc.frequency.value = 880; gain.gain.value = 0.05;
            osc.start(); setTimeout(() => {{ osc.stop(); ctx.close(); }}, 220);
          }} catch(e) {{}}
        </script>
        """,
        height=145,
    )
    with st.container(border=True):
        st.error(f"🚨 FLASH ALERT: {top.narrative} — {action} {top.primary_symbol}", icon="🚨")
        if st.button("Acknowledge Flash Alert", key=f"ack_{top.id}"):
            p.acknowledge_flash_alert(str(top.id))
            st.rerun()


def enable_auto_refresh(seconds: int) -> None:
    seconds = max(20, int(seconds))
    components.html(
        f"""
        <script>
          setTimeout(function() {{ window.parent.location.reload(); }}, {seconds * 1000});
        </script>
        """,
        height=0,
    )


def main():
    st.set_page_config(page_title="Signal Trading Platform V5.1", layout="wide")
    p = TradingPlatform()
    s = p.settings()

    if s.get("watchdog_enabled"):
        enable_auto_refresh(int(s.get("watchdog_interval_seconds", 60)))
        # A Streamlit app cannot truly run while closed/asleep. This cycle executes on each rerun.
        result = p.watchdog_cycle(max_signals=int(s.get("watchdog_max_signals", 80)))
        st.toast(f"Watchdog cycle: {result['signals']} signals, {result['new_flash_alerts']} new flash alert(s)")

    flash_banner(p)
    st.title("🦈 Signal Trading Platform V5.1 — Flash + Portable Watchdog")
    st.caption("Live-only intelligence, 2-feed confirmation, sanity validation, Strong Buy/Buy/Hold/Sell/Strong Sell advice, UI flash alerts, and local CLI monitoring.")

    with st.sidebar:
        st.header("Controls")
        max_sigs = st.slider("Signals per scan", 10, 150, 60, 5)
        if st.button("Run Shark Scan", type="primary"):
            n = p.scan_signals(max_sigs)
            st.success(f"Collected {n} live signals and rebuilt the ranked queue")
        if st.button("Run Watchdog Cycle Now"):
            res = p.watchdog_cycle(max_signals=max_sigs)
            st.success(f"Watchdog: {res['signals']} signals, {res['new_flash_alerts']} new flash alert(s)")
        if st.button("Morning Radar"):
            n = p.morning_radar()
            st.success(f"Morning radar collected {n} live signals")
        if st.button("Mark-to-market"):
            p.status()
            st.success("Positions refreshed")
        if st.button("Reset paper account"):
            p.reset()
            st.warning("Paper account reset")
        st.divider()
        s = p.settings()
        backend = st.selectbox("Execution backend", ["paper", "ibkr"], index=0 if s.get("broker_backend") == "paper" else 1)
        min_score = st.slider("Minimum shark score", 0, 100, int(s.get("min_shark_score", 70)))
        cash = st.number_input("Starting / reset cash", value=float(s.get("starting_cash", 10000.0)), step=1000.0)
        halted = st.checkbox("Kill switch: halt new trades", value=bool(s.get("trading_halted", False)))
        st.subheader("Flash / Watchdog")
        flash_on = st.checkbox("Enable Flash Alerts", value=bool(s.get("flash_alerts_enabled", True)))
        flash_score = st.slider("Flash min score", 70, 100, int(s.get("flash_min_score", 82)))
        flash_conf = st.slider("Flash min confidence", 70, 100, int(s.get("flash_min_confidence", 78)))
        watchdog_on = st.checkbox("UI auto-watchdog", value=bool(s.get("watchdog_enabled", False)))
        watchdog_seconds = st.number_input("UI refresh seconds", min_value=20, max_value=900, value=int(s.get("watchdog_interval_seconds", 60)), step=10)
        watchdog_max = st.number_input("Watchdog signals/cycle", min_value=20, max_value=200, value=int(s.get("watchdog_max_signals", 80)), step=10)
        if st.button("Save settings"):
            p.update_settings({
                "broker_backend": backend,
                "min_shark_score": min_score,
                "starting_cash": cash,
                "trading_halted": halted,
                "flash_alerts_enabled": flash_on,
                "flash_min_score": flash_score,
                "flash_min_confidence": flash_conf,
                "watchdog_enabled": watchdog_on,
                "watchdog_interval_seconds": int(watchdog_seconds),
                "watchdog_max_signals": int(watchdog_max),
            })
            st.success("Settings saved")
            st.rerun()

    status = p.status()
    risk = p.risk_snapshot()
    rel = p.feed_reliability_report()
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("Equity", f"${status.get('equity', 0):,.2f}")
    c2.metric("Cash", f"${status.get('cash_balance', 0):,.2f}")
    c3.metric("Drawdown", f"{risk.get('drawdown_pct', 0):.2f}%")
    c4.metric("Risk", risk.get("risk_status", "NORMAL"))
    c5.metric("Feeds", rel.get("system_status", "SAFE_MODE"))
    c6.metric("Backend", status.get("backend", "paper"))
    c7.metric("Flash", len(p.flash_alerts_df()[p.flash_alerts_df().get("acknowledged", pd.Series(dtype=bool)) != True]) if not p.flash_alerts_df().empty else 0)  # noqa: E712

    tabs = st.tabs(["🚨 Flash", "🦈 Shark Alerts", "Action Advice", "Risk", "Feed Reliability", "Signal Feed", "Feed Health", "Orders/Fills", "Positions", "Journal", "Settings"])
    with tabs[0]:
        st.subheader("Flash Alert Queue")
        flash = p.flash_alerts_df()
        if flash.empty:
            st.info("No flash alerts. Only strongest confirmed anomalies are promoted here.")
        else:
            st.dataframe(flash.sort_values("created_at", ascending=False), width="stretch", hide_index=True)
            for _, row in flash[flash["acknowledged"] != True].iterrows():  # noqa: E712
                if st.button(f"Acknowledge {row.narrative} ({row.action})", key=f"ack_tab_{row.id}"):
                    p.acknowledge_flash_alert(str(row.id))
                    st.rerun()
        hist = p.flash_history_df()
        if not hist.empty:
            st.subheader("Flash History")
            st.dataframe(hist.tail(100), width="stretch", hide_index=True)
        st.info("For always-on monitoring independent of Streamlit, run: python monitor.py --interval 60")

    with tabs[1]:
        alerts = p.alerts_df()
        if alerts.empty:
            st.info("Run a Shark Scan to populate the ranked opportunity queue.")
        else:
            top = alerts.sort_values("shark_score", ascending=False)
            for _, a in top.iterrows():
                with st.container(border=True):
                    h1, h2, h3, h4, h5, h6 = st.columns([2, 1, 1, 1, 1, 1])
                    h1.subheader(f"{badge(float(a.shark_score))} {a.narrative}")
                    h2.metric("Score", a.shark_score)
                    h3.metric("Shock", a.shock_score)
                    h4.metric("Confirm", a.confirmation_score)
                    h5.metric("Fresh", a.freshness_score)
                    h6.metric("Tradable", a.tradability_score)
                    meta = a.metadata if isinstance(a.metadata, dict) else {}
                    advice = meta.get("advice", {}) if isinstance(meta.get("advice"), dict) else {}
                    st.write(f"**Status:** {a.status} | **Direction:** {a.direction} | **Primary:** {a.primary_symbol} | **Action:** {a.action} | **Trend:** {advice.get('trend_stage', 'n/a')}")
                    st.write("**Evidence:** " + " · ".join(a.evidence))
                    if advice:
                        st.success(f"Advice: {str(advice.get('action')).replace('_', ' ')} — {advice.get('reason')}")
                    if a.warnings:
                        st.warning(" | ".join(a.warnings))
                    inst = pd.DataFrame(a.instruments)
                    if not inst.empty:
                        st.dataframe(inst, width="stretch", hide_index=True)
                    colA, colB = st.columns([1, 4])
                    dollars = colA.number_input("Paper $", min_value=100.0, value=800.0, step=100.0, key=f"dol_{a.id}")
                    if colB.button("Paper trade top mapped instrument", key=f"trade_{a.id}"):
                        res = p.auto_paper_top_alert(a.id, dollars)
                        if res.get("ok"):
                            st.success(f"Paper order {res['order']['status']}: {res['order']['symbol']}")
                        else:
                            st.error(res.get("error"))
    with tabs[2]:
        advice = p.advice_df()
        st.caption("Action scale is preserved: Strong Buy, Buy, Hold, Sell, Strong Sell. REDUCE may appear when risk says trim rather than fully sell.")
        if advice.empty:
            st.info("No action advice yet. Run a Shark Scan.")
        else:
            show = advice.copy()
            if "action" in show.columns:
                show["action"] = show["action"].astype(str).str.replace("_", " ")
            st.dataframe(show, width="stretch", hide_index=True)
    with tabs[3]:
        snap = p.risk_snapshot()
        cols = st.columns(5)
        cols[0].metric("Risk Status", snap.get("risk_status"))
        cols[1].metric("Daily P&L", f"${snap.get('daily_realized_pnl', 0):,.2f}")
        cols[2].metric("Exposure", f"{snap.get('exposure_pct', 0):.2f}%")
        cols[3].metric("Open Positions", snap.get("open_positions", 0))
        cols[4].metric("Loss Streak", snap.get("consecutive_losses", 0))
        if snap.get("messages"):
            st.warning(" | ".join(snap.get("messages", [])))
        st.json(snap)
    with tabs[4]:
        st.json(rel)
        st.caption("LIVE_READY allows trade advice; SAFE_MODE still monitors but blocks trade-candidate promotion.")
    with tabs[5]:
        df = p.signals_df()
        if df.empty:
            st.info("No signals yet.")
        else:
            show = df.copy()
            show["metadata"] = show.get("metadata", pd.Series([{} for _ in range(len(show))]))
            show["narrative"] = show["metadata"].apply(lambda x: x.get("narrative") if isinstance(x, dict) else None)
            show["feed_type"] = show["metadata"].apply(lambda x: x.get("feed_type") if isinstance(x, dict) else None)
            show["prob_change"] = show["metadata"].apply(lambda x: x.get("probability_change_pct") if isinstance(x, dict) else None)
            show["volume_z"] = show["metadata"].apply(lambda x: x.get("volume_zscore") if isinstance(x, dict) else None)
            cols = ["created_at", "source", "feed_type", "symbol", "direction", "confidence", "magnitude", "narrative", "prob_change", "volume_z", "title"]
            for col in cols:
                if col not in show.columns:
                    show[col] = None
            st.dataframe(show[cols], width="stretch", hide_index=True)
    with tabs[6]:
        health = p.feed_health_df()
        if health.empty:
            st.info("No feed health yet. Run a live Shark Scan.")
        else:
            st.dataframe(health, width="stretch", hide_index=True)
    with tabs[7]:
        st.subheader("Orders")
        orders = p.orders_df()
        st.dataframe(orders, width="stretch", hide_index=True) if not orders.empty else st.info("No orders yet.")
        st.subheader("Fills")
        fills = p.fills_df()
        st.dataframe(fills, width="stretch", hide_index=True) if not fills.empty else st.info("No fills yet.")
    with tabs[8]:
        st.dataframe(p.positions_df(), width="stretch", hide_index=True)
    with tabs[9]:
        journal = p.journal_df().tail(250)
        st.dataframe(journal, width="stretch", hide_index=True) if not journal.empty else st.info("No journal entries yet.")
    with tabs[10]:
        st.json(p.settings())
        st.info("Streamlit Community may sleep. For reliable always-on monitoring, run the local worker: python monitor.py --interval 60")

if __name__ == "__main__":
    main()
