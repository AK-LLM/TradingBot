from __future__ import annotations
import html
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from app.platform import TradingPlatform


CA_SUFFIXES = (".TO", ".V", ".CN", ".NE")


def is_canadian_symbol(sym: str) -> bool:
    if not sym:
        return False
    return str(sym).upper().endswith(CA_SUFFIXES)


def badge(score: float) -> str:
    if score >= 75:
        return "🦈 SHARK"
    if score >= 55:
        return "👀 WATCH"
    return "⚪ LOW"


def stage_badge(stage: str) -> str:
    return {
        "SCOUT": "🔍 SCOUT",
        "STALKING": "🦈 STALKING",
        "STRIKING": "⚡ STRIKING",
        "LATE": "🌊 LATE",
    }.get(stage, stage)


def urgency_badge(urgency: str) -> str:
    return {
        "CRITICAL": "🔴 CRITICAL",
        "HIGH": "🟠 HIGH",
        "MEDIUM": "🟡 MEDIUM",
        "LOW": "🟢 LOW",
    }.get(urgency, urgency)


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


def stop_alert_banner(p: TradingPlatform) -> None:
    """V5.6: Surface critical stop alerts at top of page."""
    stops_df = p.stop_alerts_df()
    if stops_df.empty:
        return
    critical = stops_df[stops_df["urgency"] == "CRITICAL"]
    if critical.empty:
        return
    for _, row in critical.iterrows():
        st.error(
            f"🛑 HARD STOP HIT: **{row.symbol}** at ${row.current_price} ({row.pct_from_entry:+.1f}% from entry). Suggested action: **{row.suggested_action}**. {row.reason}",
            icon="🛑"
        )


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


def render_canada_view(p: TradingPlatform) -> None:
    """Dedicated Canadian intelligence view."""
    st.subheader("🇨🇦 Canadian Intelligence")
    st.caption("Filtered view of Canadian-specific feeds, signals, instruments, and exposures.")

    st.markdown("### Canadian Feed Health")
    health = p.feed_health_df()
    if not health.empty:
        ca_keywords = ["canada", "canadian", "sedi", "statcan", "boc"]
        ca_health = health[health["feed"].str.lower().str.contains("|".join(ca_keywords), na=False)]
        if ca_health.empty:
            st.info("Canadian feeds (Bank of Canada, SEDI, StatCan) have not run yet. Trigger a Shark Scan.")
        else:
            st.dataframe(ca_health, width="stretch", hide_index=True)
    else:
        st.info("No feed health data yet. Run a Shark Scan.")

    st.markdown("### Canadian Signals (live)")
    signals_df = p.signals_df()
    if signals_df.empty:
        st.info("No signals yet.")
    else:
        def is_ca_signal(row):
            source = str(row.get("source", "")).lower()
            symbol = str(row.get("symbol", ""))
            meta = row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {}
            if any(k in source for k in ["canada", "sedi", "statcan", "bank of canada"]):
                return True
            if is_canadian_symbol(symbol):
                return True
            if meta.get("jurisdiction") == "CA":
                return True
            if meta.get("narrative") == "canada_specific":
                return True
            return False
        ca_mask = signals_df.apply(is_ca_signal, axis=1)
        ca_signals = signals_df[ca_mask]
        if ca_signals.empty:
            st.info("No Canadian-specific signals fired this scan.")
        else:
            display_cols = ["created_at", "source", "symbol", "direction", "confidence", "title"]
            available = [c for c in display_cols if c in ca_signals.columns]
            st.dataframe(ca_signals[available].sort_values("confidence", ascending=False),
                         width="stretch", hide_index=True)

    st.markdown("### Alerts Featuring Canadian Instruments")
    alerts = p.alerts_df()
    if not alerts.empty:
        ca_alerts = []
        for _, a in alerts.iterrows():
            instruments = a.get("instruments", []) if isinstance(a.get("instruments"), list) else []
            ca_instruments = [i for i in instruments if is_canadian_symbol(i.get("symbol", ""))]
            if is_canadian_symbol(a.primary_symbol) or ca_instruments:
                ca_alerts.append({
                    "narrative": a.narrative,
                    "primary_symbol": a.primary_symbol,
                    "direction": a.direction,
                    "shark_score": a.shark_score,
                    "status": a.status,
                    "ca_instruments": ", ".join([i.get("symbol", "") for i in ca_instruments]) or "(direct)",
                })
        if ca_alerts:
            st.dataframe(pd.DataFrame(ca_alerts), width="stretch", hide_index=True)
        else:
            st.info("No active alerts feature Canadian instruments. Canadian instruments are mapped across 22 narratives.")

    st.markdown("### Canadian Constellations")
    constellations = p.constellations_df()
    if not constellations.empty:
        ca_const = constellations[
            (constellations["pattern_name"] == "Canadian Macro Divergence") |
            (constellations["primary_symbol"].apply(is_canadian_symbol)) |
            (constellations["primary_narrative"] == "canada_specific")
        ]
        if ca_const.empty:
            st.info("No Canadian-specific constellation patterns detected this scan.")
        else:
            st.dataframe(ca_const[["pattern_name", "stage", "confidence", "direction", "primary_symbol", "description"]],
                         width="stretch", hide_index=True)
    else:
        st.info("No constellations detected yet.")

    st.markdown("### Canadian Instrument Coverage Map")
    from app.instrument_map import NARRATIVE_MAP
    ca_coverage = []
    for narrative, instruments in NARRATIVE_MAP.items():
        ca_inst = [i for i in instruments if is_canadian_symbol(i.get("symbol", ""))]
        if ca_inst:
            ca_coverage.append({
                "narrative": narrative,
                "ca_instruments": ", ".join([i["symbol"] for i in ca_inst]),
                "count": len(ca_inst),
            })
    if ca_coverage:
        cov_df = pd.DataFrame(ca_coverage).sort_values("count", ascending=False)
        st.dataframe(cov_df, width="stretch", hide_index=True)
        st.caption(f"Total: {sum(c['count'] for c in ca_coverage)} Canadian instruments across {len(ca_coverage)} narratives.")


def render_constellations_tab(p: TradingPlatform) -> None:
    """V5.5: Show constellation patterns with lifecycle stages."""
    summary = p.constellation_summary()
    cols = st.columns(5)
    cols[0].metric("Total", summary.get("total_constellations", 0))
    by_stage = summary.get("by_stage", {})
    cols[1].metric("🔍 SCOUT", by_stage.get("SCOUT", 0))
    cols[2].metric("🦈 STALKING", by_stage.get("STALKING", 0))
    cols[3].metric("⚡ STRIKING", by_stage.get("STRIKING", 0))
    cols[4].metric("🌊 LATE", by_stage.get("LATE", 0))

    st.caption("Constellations are multi-feed patterns. SCOUT = early signal (you're ahead), LATE = consensus formed (you're behind).")

    constellations_df = p.constellations_df()
    if constellations_df.empty:
        st.info("No constellation patterns detected yet. Run a Shark Scan to populate.")
        return

    fcol1, fcol2, fcol3 = st.columns(3)
    stage_filter = fcol1.multiselect("Stage", ["SCOUT", "STALKING", "STRIKING", "LATE"],
                                      default=["SCOUT", "STALKING", "STRIKING"])
    direction_filter = fcol2.multiselect("Direction", ["BUY", "SELL", "WATCH"], default=["BUY", "SELL"])
    pattern_filter = fcol3.multiselect("Pattern", sorted(constellations_df["pattern_name"].dropna().unique()))

    filtered = constellations_df.copy()
    if stage_filter:
        filtered = filtered[filtered["stage"].isin(stage_filter)]
    if direction_filter:
        filtered = filtered[filtered["direction"].isin(direction_filter)]
    if pattern_filter:
        filtered = filtered[filtered["pattern_name"].isin(pattern_filter)]

    if filtered.empty:
        st.info("No constellations match the selected filters.")
        return

    for _, c in filtered.iterrows():
        with st.container(border=True):
            h1, h2, h3, h4 = st.columns([3, 1, 1, 1])
            h1.subheader(f"⭐ {c.pattern_name}")
            h2.metric("Stage", stage_badge(c.stage))
            h3.metric("Direction", c.direction)
            h4.metric("Confidence", f"{float(c.confidence):.2f}")
            st.write(f"**Narrative:** `{c.primary_narrative}` · **Symbol:** `{c.primary_symbol}`")
            if c.contributing_feeds is not None and len(c.contributing_feeds) > 0:
                feeds_str = ', '.join(c.contributing_feeds) if isinstance(c.contributing_feeds, list) else str(c.contributing_feeds)
                st.write(f"**Contributing feeds:** {feeds_str}")
            st.write(f"**Description:** {c.description}")
            st.info(f"**Why it matters:** {c.why_it_matters}")
            if c.velocity_context:
                st.caption(f"Velocity: {c.velocity_context}")


def render_velocity_tab(p: TradingPlatform) -> None:
    """V5.5: Velocity tracking."""
    summary = p.velocity_summary()
    cols = st.columns(5)
    cols[0].metric("Channels", summary.get("total_channels", 0))
    cols[1].metric("⚡ Up", summary.get("accelerating_up", 0))
    cols[2].metric("📉 Down", summary.get("accelerating_down", 0))
    cols[3].metric("⏸️ Stable", summary.get("stable", 0))
    cols[4].metric("✨ New", summary.get("new_channels", 0))

    st.caption("Velocity tracks how signal STRENGTH changes over time. A signal at 60 that was at 20 yesterday matters more than one at 80 that's been at 80 all week.")

    velocity_df = p.velocity_df()
    if velocity_df.empty:
        st.info("Velocity tracking needs at least 4 scans to compute meaningful acceleration.")
        return

    if "acceleration" in velocity_df.columns:
        priority = {"ACCELERATING_UP": 0, "NEW": 1, "ACCELERATING_DOWN": 2, "STABLE": 3}
        velocity_df = velocity_df.copy()
        velocity_df["_priority"] = velocity_df["acceleration"].map(priority).fillna(99)
        velocity_df = velocity_df.sort_values(["_priority", "current_strength"], ascending=[True, False])
        velocity_df = velocity_df.drop(columns=["_priority"])

    st.dataframe(velocity_df, width="stretch", hide_index=True)


def render_risk_intelligence_tab(p: TradingPlatform) -> None:
    """V5.6: Stop alerts, correlation/sector exposures, VIX-adjusted sizing."""
    summary = p.risk_intelligence_summary()

    cols = st.columns(4)
    cols[0].metric("🛑 Critical Stops", summary.get("stop_alerts_critical", 0))
    cols[1].metric("⚠️ High Stops", summary.get("stop_alerts_high", 0))
    cols[2].metric("Total Breaches", summary.get("total_breaches", 0))
    vix_mult = summary.get("vix_size_multiplier", 1.0)
    vix_label = "Full size" if vix_mult >= 1 else f"{int(vix_mult*100)}% (regime cut)"
    cols[3].metric("VIX Multiplier", f"{vix_mult:.2f}", help=vix_label)

    st.markdown("### 🛑 Auto-Stop Alerts")
    stops = p.stop_alerts_df()
    if stops.empty:
        st.info("No stop alerts. Open positions are within stop thresholds.")
    else:
        s = p.settings()
        st.caption(f"Soft stop fires REDUCE at {s.get('auto_stop_pct', 0.04)*100:.0f}% loss · Hard stop fires SELL at {s.get('hard_stop_pct', 0.07)*100:.0f}% loss · Trailing stop fires REDUCE at {s.get('trail_giveback_pct', 0.40)*100:.0f}% giveback of gains.")
        for _, srow in stops.iterrows():
            container_func = st.error if srow.urgency == "CRITICAL" else (st.warning if srow.urgency == "HIGH" else st.info)
            container_func(
                f"{urgency_badge(srow.urgency)} **{srow.symbol}** @ ${srow.current_price} ({srow.pct_from_entry:+.1f}% from entry, {srow.pct_from_high:+.1f}% from high) → **{srow.suggested_action}** · {srow.reason}"
            )

    st.markdown("### 🔗 Correlation Group Exposure")
    corr = p.correlation_exposures_df()
    if corr.empty:
        st.info("No positions yet — no correlation exposure to display.")
    else:
        max_pct = p.settings().get("max_correlation_group_pct", 0.20) * 100
        st.caption(f"Max per correlation group: {max_pct:.0f}%. XLE+XOM+CVX count as one 'energy' bucket.")
        st.dataframe(corr, width="stretch", hide_index=True)
        breaches = corr[corr["breach"] == True]  # noqa: E712
        if not breaches.empty:
            st.error(f"🔴 {len(breaches)} correlation group(s) in BREACH of cap.")

    st.markdown("### 🏢 Sector Exposure")
    sectors = p.sector_exposures_df()
    if sectors.empty:
        st.info("No positions yet — no sector exposure to display.")
    else:
        max_sec = p.settings().get("max_sector_pct", 0.30) * 100
        st.caption(f"Max per sector: {max_sec:.0f}%.")
        st.dataframe(sectors, width="stretch", hide_index=True)


def conviction_badge(conviction: str) -> str:
    return {
        "HIGH": "🟢 HIGH",
        "MEDIUM": "🟡 MEDIUM",
        "LOW": "🟠 LOW",
    }.get(conviction, conviction)


def urgency_badge_decision(urgency: str) -> str:
    return {
        "ACT_NOW": "⚡ ACT NOW",
        "TODAY": "📅 TODAY",
        "THIS_WEEK": "🗓️ THIS WEEK",
        "WATCH": "👁️ WATCH",
    }.get(urgency, urgency)


def action_emoji(action: str) -> str:
    return {
        "ENTER_NEW": "🆕",
        "ADD_TO_EXISTING": "➕",
        "AVERAGE_DOWN": "⬇️",
        "TAKE_PARTIAL_PROFIT": "💰",
        "REDUCE": "📉",
        "EXIT_FULL": "🚪",
        "AVOID": "🚫",
        "WAIT": "⏸️",
    }.get(action, "•")


def render_decisions_tab(p: TradingPlatform) -> None:
    """V5.7: Primary decision queue. The 'offload' surface."""
    summary = p.decision_summary()
    cols = st.columns(5)
    cols[0].metric("Total", summary.get("total", 0))
    cols[1].metric("⚡ ACT NOW", summary.get("by_urgency", {}).get("ACT_NOW", 0))
    cols[2].metric("🟢 HIGH conviction", summary.get("by_conviction", {}).get("HIGH", 0))
    cols[3].metric("🤖 Auto-eligible", summary.get("auto_executable", 0))
    auto_status = "🟢 ACTIVE" if p.is_auto_execute_active() else "🔴 DISABLED"
    cols[4].metric("Auto-Execute", auto_status)

    backend = p.settings().get("broker_backend", "paper")
    if backend == "ibkr":
        st.warning("🛡️ IBKR mode: Auto-execute is HARDCODED OFF for real-money safety. Decisions still generate, but you must click Execute manually.")
    elif p.is_auto_execute_active():
        st.success("🤖 Paper auto-execute is ACTIVE. HIGH-conviction + ACT_NOW + entry/add/reduce/exit decisions will fire automatically on each scan.")
    else:
        st.info("Auto-execute is currently disabled. Toggle in Settings → V5.7 Decision Engine.")

    decisions_df = p.decisions_df()
    if decisions_df.empty:
        st.info("No active decisions. Run a Shark Scan to populate.")
        # Still show history
        history = p.decision_history_df()
        if not history.empty:
            with st.expander(f"Decision History ({len(history)} past decisions)"):
                st.dataframe(history.tail(50), width="stretch", hide_index=True)
        return

    # Filter
    fc1, fc2, fc3 = st.columns(3)
    urgency_filter = fc1.multiselect("Urgency", ["ACT_NOW", "TODAY", "THIS_WEEK", "WATCH"],
                                      default=["ACT_NOW", "TODAY"])
    conviction_filter = fc2.multiselect("Conviction", ["HIGH", "MEDIUM", "LOW"],
                                         default=["HIGH", "MEDIUM"])
    action_filter = fc3.multiselect("Action",
                                     sorted(decisions_df["action"].dropna().unique()))

    filtered = decisions_df.copy()
    if urgency_filter:
        filtered = filtered[filtered["urgency"].isin(urgency_filter)]
    if conviction_filter:
        filtered = filtered[filtered["conviction"].isin(conviction_filter)]
    if action_filter:
        filtered = filtered[filtered["action"].isin(action_filter)]

    if filtered.empty:
        st.info("No decisions match the selected filters.")
        return

    st.markdown("### Active Decisions")
    for _, d in filtered.iterrows():
        full_decision = p.get_decision(d.id)
        if not full_decision:
            continue

        # Card
        with st.container(border=True):
            # Header row
            h1, h2, h3, h4 = st.columns([3, 1, 1, 1])
            ca_marker = " 🇨🇦" if is_canadian_symbol(d.symbol) else ""
            auto_marker = " 🤖" if d.auto_executable else ""
            h1.subheader(f"{action_emoji(d.action)} {d.action.replace('_', ' ')} — {d.symbol}{ca_marker}{auto_marker}")
            h2.metric("Urgency", urgency_badge_decision(d.urgency))
            h3.metric("Conviction", conviction_badge(d.conviction))
            stage_str = f" [{d.constellation_stage}]" if d.constellation_stage else ""
            h4.caption(f"⭐ {d.constellation_pattern}{stage_str}" if d.constellation_pattern else f"📊 {d.primary_driver}")

            # The one-line summary - the offload surface
            st.success(f"**{d.one_line}**")

            # Plan + sizing details
            sizing = full_decision.get("sizing", {}) or {}
            plan = full_decision.get("plan", {}) or {}

            pcol1, pcol2, pcol3, pcol4 = st.columns(4)
            pcol1.metric("Suggested $", f"${sizing.get('suggested_dollars', 0):,.0f}",
                          help=f"Base ${sizing.get('base_dollars', 0):,.0f} × VIX mult {sizing.get('vix_multiplier', 1):.2f}")
            pcol2.metric("Quantity", f"{sizing.get('suggested_quantity', 0)}")
            pcol3.metric("% Equity", f"{sizing.get('pct_of_equity', 0):.2f}%")
            pcol4.metric("R:R Ratio", f"{plan.get('risk_reward_ratio', 0)}:1")

            ecol1, ecol2, ecol3, ecol4 = st.columns(4)
            ecol1.metric("Entry", f"${plan.get('entry_price', 0):.2f}",
                          help=f"Zone: ${plan.get('entry_zone_low', 0):.2f} – ${plan.get('entry_zone_high', 0):.2f}")
            ecol2.metric("Stop", f"${plan.get('stop_price', 0):.2f}",
                          help=f"{plan.get('stop_pct_from_entry', 0):.1f}% from entry")
            ecol3.metric("First Target", f"${plan.get('first_target', 0):.2f}",
                          help=f"+{plan.get('target_pct_from_entry', 0):.1f}% from entry")
            ecol4.metric("Trail Trigger", f"${plan.get('trail_trigger', 0):.2f}",
                          help=f"Trailing stop activates at this price")

            # Why
            with st.expander("Why this decision"):
                st.write(f"**Primary driver:** {d.primary_driver}")
                st.write(f"**Confirming feeds:** {', '.join(d.confirming_feeds) if isinstance(d.confirming_feeds, list) else d.confirming_feeds}")
                st.write(f"**Velocity:** {d.velocity_context}")
                st.write(f"**Regime:** {d.regime_context}")
                st.write(f"**Reasoning:** {full_decision.get('why', '')}")
                if sizing.get("correlation_groups"):
                    st.write(f"**Correlation groups:** {', '.join(sizing['correlation_groups'])}")
                if sizing.get("headroom_remaining_pct", 0) > 0:
                    st.write(f"**Headroom:** Up to {sizing['headroom_remaining_pct']:.1f}% more equity available if thesis confirms")

            # Kill conditions
            kill_conds = full_decision.get("kill_conditions", []) or []
            if kill_conds:
                with st.expander("⚠️ Kill conditions (when to exit/reverse)"):
                    for kc in kill_conds:
                        st.markdown(f"- {kc}")

            # Action buttons
            bcol1, bcol2, bcol3 = st.columns([1, 1, 4])
            if bcol1.button(f"✓ Execute", key=f"exec_{d.id}", type="primary"):
                res = p.execute_decision(d.id)
                if res.get("ok"):
                    st.success(f"Executed: {d.symbol} {d.action}")
                    st.rerun()
                else:
                    st.error(f"Execution failed: {res.get('error', 'Unknown')}")
            if bcol2.button(f"⊘ Skip", key=f"skip_{d.id}"):
                p.skip_decision(d.id)
                st.info(f"Skipped: {d.symbol}")
                st.rerun()

    # History at the bottom
    history = p.decision_history_df()
    if not history.empty:
        with st.expander(f"Decision History ({len(history)} past decisions)"):
            st.dataframe(history.tail(50).sort_values("created_at", ascending=False),
                         width="stretch", hide_index=True)


def render_settings_tab(p: TradingPlatform) -> None:
    s = p.settings()
    st.subheader("All Settings")

    with st.expander("Account / Trading", expanded=True):
        st.json({k: v for k, v in s.items() if k in {
            "broker_backend", "starting_cash", "cash_balance", "trading_halted",
            "min_shark_score", "max_daily_loss", "max_drawdown_pct",
            "risk_per_trade_pct", "max_position_pct", "max_trade_pct",
            "max_total_exposure_pct", "max_open_positions", "max_consecutive_losses",
            "symbol_cooldown_minutes", "max_spread_bps", "default_stop_pct",
        }})

    with st.expander("Confirmation / Sanity"):
        st.json({k: v for k, v in s.items() if k in {
            "min_independent_sources", "min_feed_type_confirmations",
            "min_freshness_score", "min_tradability_score", "min_confirmation_score",
            "max_move_before_entry_pct", "minimum_live_feeds_required", "minimum_feed_types_required",
        }})

    with st.expander("Flash / Watchdog"):
        st.json({k: v for k, v in s.items() if k.startswith("flash_") or k.startswith("watchdog_")})

    with st.expander("V5.6 Risk Intelligence", expanded=True):
        st.markdown("**Settings for auto-stop, trailing-stop, correlation, sector, and VIX-adjusted sizing logic:**")
        v56_keys = ["auto_stop_pct", "hard_stop_pct", "trail_trigger_pct",
                    "trail_giveback_pct", "max_correlation_group_pct",
                    "max_sector_pct", "vix_panic_threshold", "vix_elevated_threshold"]
        st.json({k: s.get(k) for k in v56_keys})

        st.markdown("---")
        st.markdown("**Edit V5.6 Settings:**")
        c1, c2 = st.columns(2)
        new_auto_stop = c1.slider("Soft stop % (REDUCE alert)", 1.0, 10.0,
                                   float(s.get("auto_stop_pct", 0.04)) * 100, 0.5) / 100
        new_hard_stop = c2.slider("Hard stop % (SELL alert)", 3.0, 15.0,
                                   float(s.get("hard_stop_pct", 0.07)) * 100, 0.5) / 100
        c3, c4 = st.columns(2)
        new_trail_trig = c3.slider("Trail trigger % (in profit)", 3.0, 20.0,
                                    float(s.get("trail_trigger_pct", 0.06)) * 100, 0.5) / 100
        new_trail_give = c4.slider("Trail giveback %", 20.0, 80.0,
                                    float(s.get("trail_giveback_pct", 0.40)) * 100, 5.0) / 100
        c5, c6 = st.columns(2)
        new_corr = c5.slider("Max correlation group %", 5.0, 40.0,
                              float(s.get("max_correlation_group_pct", 0.20)) * 100, 1.0) / 100
        new_sec = c6.slider("Max sector %", 10.0, 60.0,
                             float(s.get("max_sector_pct", 0.30)) * 100, 1.0) / 100
        c7, c8 = st.columns(2)
        new_vix_p = c7.slider("VIX panic threshold", 25, 50, int(s.get("vix_panic_threshold", 30)))
        new_vix_e = c8.slider("VIX elevated threshold", 15, 30, int(s.get("vix_elevated_threshold", 20)))

        if st.button("Save V5.6 Risk Settings"):
            p.update_settings({
                "auto_stop_pct": new_auto_stop, "hard_stop_pct": new_hard_stop,
                "trail_trigger_pct": new_trail_trig, "trail_giveback_pct": new_trail_give,
                "max_correlation_group_pct": new_corr, "max_sector_pct": new_sec,
                "vix_panic_threshold": new_vix_p, "vix_elevated_threshold": new_vix_e,
            })
            st.success("V5.6 risk settings saved")
            st.rerun()

    with st.expander("🎯 V5.7 Decision Engine", expanded=True):
        st.markdown("**Settings for the decision packager and auto-execute behavior:**")
        backend = s.get("broker_backend", "paper")
        if backend != "paper":
            st.error("🛡️ Auto-execute is HARDCODED OFF for IBKR. Real-money execution always requires manual click. Switch to paper backend to enable auto-execute.")

        v57_keys = ["decision_min_score", "decision_base_dollars", "decision_add_dollars",
                    "decision_avg_down_dollars", "first_target_pct", "time_stop_days",
                    "enable_average_down", "enable_auto_execute"]
        st.json({k: s.get(k) for k in v57_keys})

        st.markdown("---")
        st.markdown("**Edit V5.7 Settings:**")
        d1, d2 = st.columns(2)
        new_dec_min_score = d1.slider("Decision min shark score", 50, 95,
                                       int(s.get("decision_min_score", 65)))
        new_dec_base = d2.number_input("Default $ for ENTER_NEW", min_value=100.0,
                                        value=float(s.get("decision_base_dollars", 800)), step=100.0)
        d3, d4 = st.columns(2)
        new_dec_add = d3.number_input("Default $ for ADD", min_value=100.0,
                                       value=float(s.get("decision_add_dollars", 400)), step=50.0)
        new_dec_avg = d4.number_input("Default $ for AVERAGE_DOWN", min_value=100.0,
                                       value=float(s.get("decision_avg_down_dollars", 400)), step=50.0)
        d5, d6 = st.columns(2)
        new_first_target = d5.slider("First profit target %", 3.0, 25.0,
                                      float(s.get("first_target_pct", 0.08)) * 100, 0.5) / 100
        new_time_stop = d6.slider("Time stop (days)", 3, 60, int(s.get("time_stop_days", 14)))
        d7, d8 = st.columns(2)
        new_avg_down = d7.checkbox("Enable AVERAGE_DOWN action",
                                    value=bool(s.get("enable_average_down", True)),
                                    help="If on, engine may suggest averaging down on positions 5-15% in the red when thesis reinforces. Max 1 average-down per position.")
        new_auto_exec = d8.checkbox("Enable AUTO-EXECUTE (paper only)",
                                     value=bool(s.get("enable_auto_execute", True)),
                                     help="If on AND backend is paper, HIGH-conviction + ACT_NOW decisions auto-fire on each scan. HARDCODED OFF for IBKR.")

        if st.button("Save V5.7 Decision Settings"):
            p.update_settings({
                "decision_min_score": new_dec_min_score,
                "decision_base_dollars": new_dec_base,
                "decision_add_dollars": new_dec_add,
                "decision_avg_down_dollars": new_dec_avg,
                "first_target_pct": new_first_target,
                "time_stop_days": new_time_stop,
                "enable_average_down": new_avg_down,
                "enable_auto_execute": new_auto_exec,
            })
            st.success("V5.7 decision settings saved")
            st.rerun()


def main():
    st.set_page_config(page_title="Signal Trading Platform V6.1", layout="wide")
    p = TradingPlatform()
    s = p.settings()

    if s.get("watchdog_enabled"):
        enable_auto_refresh(int(s.get("watchdog_interval_seconds", 60)))
        try:
            result = p.watchdog_cycle(max_signals=int(s.get("watchdog_max_signals", 80)))
            if result.get("error"):
                st.toast(f"⚠️ Watchdog cycle had errors: {result['error'][:80]}", icon="⚠️")
            else:
                st.toast(f"Watchdog cycle: {result['signals']} signals, {result['new_flash_alerts']} new flash alert(s)")
        except Exception as e:
            st.toast(f"⚠️ Watchdog crashed: {type(e).__name__}", icon="⚠️")

    flash_banner(p)
    stop_alert_banner(p)

    st.title("🦈 Signal Trading Platform V6.1 — Decision Engine + Critic + Calibration Loop")
    st.caption("🦈 34 feeds (10 sniffer feeds for front-running) · Decision packages with auto-execute (paper) · 11 constellation patterns · Velocity tracking · Auto-stops · Correlation/sector caps · VIX-adjusted sizing · Full action spectrum")

    with st.sidebar:
        st.header("Controls")
        max_sigs = st.slider("Signals per scan", 10, 150, 60, 5)
        if st.button("Run Shark Scan", type="primary"):
            try:
                n = p.scan_signals(max_sigs)
                st.success(f"Collected {n} live signals and rebuilt the ranked queue")
            except Exception as e:
                st.error(f"Scan failed: {type(e).__name__}: {str(e)[:200]}")
        if st.button("Run Watchdog Cycle Now"):
            try:
                res = p.watchdog_cycle(max_signals=max_sigs)
                if res.get("error"):
                    st.warning(f"Watchdog completed with errors: {res['error'][:120]}")
                else:
                    st.success(f"Watchdog: {res['signals']} signals, {res['new_flash_alerts']} new flash alert(s)")
            except Exception as e:
                st.error(f"Watchdog crashed: {type(e).__name__}: {str(e)[:200]}")
        if st.button("Morning Radar"):
            try:
                n = p.morning_radar()
                st.success(f"Morning radar collected {n} live signals")
            except Exception as e:
                st.error(f"Morning radar failed: {type(e).__name__}: {str(e)[:200]}")
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
                "broker_backend": backend, "min_shark_score": min_score,
                "starting_cash": cash, "trading_halted": halted,
                "flash_alerts_enabled": flash_on, "flash_min_score": flash_score,
                "flash_min_confidence": flash_conf, "watchdog_enabled": watchdog_on,
                "watchdog_interval_seconds": int(watchdog_seconds),
                "watchdog_max_signals": int(watchdog_max),
            })
            st.success("Settings saved")
            st.rerun()

    status = p.status()
    risk = p.risk_snapshot()
    rel = p.feed_reliability_report()
    risk_intel = p.risk_intelligence_summary()
    const_summary = p.constellation_summary()
    dec_summary = p.decision_summary()

    c1, c2, c3, c4, c5, c6, c7, c8, c9 = st.columns(9)
    c1.metric("Equity", f"${status.get('equity', 0):,.2f}")
    c2.metric("Cash", f"${status.get('cash_balance', 0):,.2f}")
    c3.metric("Drawdown", f"{risk.get('drawdown_pct', 0):.2f}%")
    c4.metric("Risk", risk.get("risk_status", "NORMAL"))
    c5.metric("Feeds", rel.get("system_status", "SAFE_MODE"))
    c6.metric("Flash", len(p.flash_alerts_df()[p.flash_alerts_df().get("acknowledged", pd.Series(dtype=bool)) != True]) if not p.flash_alerts_df().empty else 0)  # noqa: E712
    c7.metric("⭐ Patterns", const_summary.get("total_constellations", 0))
    c8.metric("🛑 Stops", risk_intel.get("stop_alerts_critical", 0) + risk_intel.get("stop_alerts_high", 0))
    c9.metric("🎯 Decisions", dec_summary.get("total", 0))

    tabs = st.tabs([
        "🎯 Decisions", "🚨 Flash", "🦈 Shark Alerts", "⭐ Constellations", "⚡ Velocity",
        "🛡️ Risk Intelligence", "🇨🇦 Canada View", "Action Advice", "Risk",
        "Feed Reliability", "Signal Feed", "Feed Health", "Orders/Fills",
        "Positions", "Journal", "Settings"
    ])

    with tabs[0]:
        render_decisions_tab(p)

    with tabs[1]:
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
        st.info("For always-on monitoring, run: python monitor.py --interval 60")

    with tabs[2]:
        alerts = p.alerts_df()
        if alerts.empty:
            st.info("Run a Shark Scan to populate the ranked opportunity queue.")
        else:
            top = alerts.sort_values("shark_score", ascending=False)
            for _, a in top.iterrows():
                with st.container(border=True):
                    h1, h2, h3, h4, h5, h6 = st.columns([2, 1, 1, 1, 1, 1])
                    ca_marker = " 🇨🇦" if is_canadian_symbol(a.primary_symbol) else ""
                    h1.subheader(f"{badge(float(a.shark_score))} {a.narrative}{ca_marker}")
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
                        action_str = str(advice.get('action')).replace('_', ' ')
                        if "REDUCE" in str(advice.get("action", "")):
                            st.warning(f"⚠️ Advice: {action_str} — {advice.get('reason')}")
                        else:
                            st.success(f"Advice: {action_str} — {advice.get('reason')}")
                        st.caption(f"Summary: {advice.get('confirmation_summary', '')}")
                    if a.warnings:
                        st.warning(" | ".join(a.warnings))
                    inst = pd.DataFrame(a.instruments)
                    if not inst.empty:
                        if "symbol" in inst.columns:
                            inst["jurisdiction"] = inst["symbol"].apply(lambda x: "🇨🇦 CA" if is_canadian_symbol(x) else "🇺🇸 US")
                        st.dataframe(inst, width="stretch", hide_index=True)
                    colA, colB = st.columns([1, 4])
                    dollars = colA.number_input("Paper $", min_value=100.0, value=800.0, step=100.0, key=f"dol_{a.id}")
                    if colB.button("Paper trade top mapped instrument", key=f"trade_{a.id}"):
                        res = p.auto_paper_top_alert(a.id, dollars)
                        if res.get("ok"):
                            st.success(f"Paper order {res['order']['status']}: {res['order']['symbol']}")
                        else:
                            st.error(res.get("error"))

    with tabs[3]:
        render_constellations_tab(p)

    with tabs[4]:
        render_velocity_tab(p)

    with tabs[5]:
        render_risk_intelligence_tab(p)

    with tabs[6]:
        render_canada_view(p)

    with tabs[7]:
        advice = p.advice_df()
        st.caption("Action scale: Strong Sell · Sell · REDUCE · Hold · Buy · Strong Buy. REDUCE fires when risk says trim rather than fully exit.")
        if advice.empty:
            st.info("No action advice yet. Run a Shark Scan.")
        else:
            show = advice.copy()
            if "action" in show.columns:
                show["action"] = show["action"].astype(str).str.replace("_", " ")
            st.dataframe(show, width="stretch", hide_index=True)

    with tabs[8]:
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

    with tabs[9]:
        st.json(rel)
        st.caption("LIVE_READY allows trade advice; SAFE_MODE still monitors but blocks trade-candidate promotion.")

    with tabs[10]:
        df = p.signals_df()
        if df.empty:
            st.info("No signals yet.")
        else:
            show = df.copy()
            show["metadata"] = show.get("metadata", pd.Series([{} for _ in range(len(show))]))
            show["narrative"] = show["metadata"].apply(lambda x: x.get("narrative") if isinstance(x, dict) else None)
            show["feed_type"] = show["metadata"].apply(lambda x: x.get("feed_type") if isinstance(x, dict) else None)
            show["noise"] = show["metadata"].apply(lambda x: x.get("noise_level") if isinstance(x, dict) else None)
            show["jurisdiction"] = show["metadata"].apply(lambda x: x.get("jurisdiction") if isinstance(x, dict) else None)
            show["prob_change"] = show["metadata"].apply(lambda x: x.get("probability_change_pct") if isinstance(x, dict) else None)

            fc1, fc2, fc3 = st.columns(3)
            noise_filter = fc1.multiselect("Noise level", ["low", "medium", "high"], default=[])
            jur_filter = fc2.multiselect("Jurisdiction", ["CA", "US"], default=[])
            ft_options = sorted([x for x in show["feed_type"].dropna().unique()]) if "feed_type" in show.columns else []
            ft_filter = fc3.multiselect("Feed type", ft_options)

            if noise_filter:
                show = show[show["noise"].isin(noise_filter)]
            if jur_filter:
                ca_mask = (show["jurisdiction"] == "CA") | (show["symbol"].apply(is_canadian_symbol))
                if "CA" in jur_filter and "US" not in jur_filter:
                    show = show[ca_mask]
                elif "US" in jur_filter and "CA" not in jur_filter:
                    show = show[~ca_mask]
            if ft_filter:
                show = show[show["feed_type"].isin(ft_filter)]

            cols = ["created_at", "source", "feed_type", "noise", "symbol", "direction", "confidence", "magnitude", "narrative", "jurisdiction", "prob_change", "title"]
            for col in cols:
                if col not in show.columns:
                    show[col] = None
            st.dataframe(show[cols], width="stretch", hide_index=True)

    with tabs[11]:
        health = p.feed_health_df()
        if health.empty:
            st.info("No feed health yet. Run a live Shark Scan.")
        else:
            # V5.8: Categorize feeds for clearer view
            sniffer_names = {
                "FRED Leading Indices", "Treasury Liquidity Pulse", "Credit Spreads Pulse",
                "ECB Statistical Data", "Yen Carry Trade Monitor", "SEC 8-K Material Events",
                "OpenInsider Cluster Buys", "Short Seller Reports",
                "Wikipedia Attention Anomaly", "Federal Contract Awards",
            }
            ca_keywords = ["canada", "canadian", "sedi", "statcan", "bank of canada"]
            crowd_names = {"Reddit Crowd Sentiment", "Google Trends Attention", "GDELT Global Events"}

            health_copy = health.copy()
            health_copy["category"] = health_copy["feed"].apply(
                lambda f: "🦈 Sniffer" if f in sniffer_names
                else "🇨🇦 Canadian" if any(k in f.lower() for k in ca_keywords)
                else "📢 Crowd/Attention" if f in crowd_names
                else "📊 Core"
            )

            # Summary row
            live_count = (health_copy["status"] == "live").sum()
            total = len(health_copy)
            sniffer_live = ((health_copy["category"] == "🦈 Sniffer") & (health_copy["status"] == "live")).sum()
            sniffer_total = (health_copy["category"] == "🦈 Sniffer").sum()
            cols = st.columns(4)
            cols[0].metric("Total Live", f"{live_count}/{total}")
            cols[1].metric("🦈 Sniffer Live", f"{sniffer_live}/{sniffer_total}")
            cols[2].metric("Core Live", f"{((health_copy['category']=='📊 Core') & (health_copy['status']=='live')).sum()}/{(health_copy['category']=='📊 Core').sum()}")
            cols[3].metric("🇨🇦 Canadian Live", f"{((health_copy['category']=='🇨🇦 Canadian') & (health_copy['status']=='live')).sum()}/{(health_copy['category']=='🇨🇦 Canadian').sum()}")

            # Filter
            cats = sorted(health_copy["category"].unique())
            cat_filter = st.multiselect("Filter by category", cats, default=cats)
            filtered = health_copy[health_copy["category"].isin(cat_filter)]

            st.dataframe(filtered.sort_values(["category", "status"]),
                         width="stretch", hide_index=True)

            with st.expander("ℹ️ About Sniffer Feeds (V5.8)"):
                st.markdown("""
**🦈 Sniffer Feeds** are designed for *front-running* — detecting themes/events BEFORE consensus forms:

- **FRED Leading Indices** — Geopolitical Risk, Economic Policy Uncertainty, Financial Stress, Recession Probability
- **Treasury Liquidity** — TGA balance + Reverse Repo levels (Fed liquidity early warning)
- **Credit Spreads** — HY OAS + BBB spreads (risk-off leading indicator)
- **ECB Statistical Data** — Composite Indicator of Systemic Stress (European stress)
- **Yen Carry Trade Monitor** — USDJPY moves (global risk-on/off proxy)
- **SEC 8-K Material Events** — M&A, bankruptcy, leadership changes before news
- **OpenInsider Cluster Buys** — Multiple insiders buying same name within 30 days
- **Short Seller Reports** — Hindenburg, Muddy Waters, Citron RSS
- **Wikipedia Attention** — Pre-news pageview spikes for monitored entities
- **Federal Contract Awards** — USASpending.gov $50M+ contracts to listed contractors

All are free, no paid subscriptions. Some may be in fallback mode initially as services adjust to Streamlit Cloud IPs.
                """)

    with tabs[12]:
        st.subheader("Orders")
        orders = p.orders_df()
        st.dataframe(orders, width="stretch", hide_index=True) if not orders.empty else st.info("No orders yet.")
        st.subheader("Fills")
        fills = p.fills_df()
        st.dataframe(fills, width="stretch", hide_index=True) if not fills.empty else st.info("No fills yet.")

    with tabs[13]:
        st.dataframe(p.positions_df(), width="stretch", hide_index=True)

    with tabs[14]:
        journal = p.journal_df().tail(250)
        st.dataframe(journal, width="stretch", hide_index=True) if not journal.empty else st.info("No journal entries yet.")

    with tabs[15]:
        render_settings_tab(p)
        st.info("Streamlit Community may sleep. For always-on monitoring, run: python monitor.py --interval 60")


if __name__ == "__main__":
    main()
