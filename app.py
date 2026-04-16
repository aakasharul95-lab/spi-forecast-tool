import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="SE Workpackage Estimation", layout="wide")

# ── Helpers ──────────────────────────────────────────────────────────────────

def next_week(yyww: int) -> int:
    y, w = divmod(yyww, 100)
    return (y + 1) * 100 + 1 if w >= 52 else y * 100 + (w + 1)

def gen_timeline(start: int, n: int) -> list[int]:
    weeks = [start]
    for _ in range(n - 1):
        weeks.append(next_week(weeks[-1]))
    return weeks

def fmt_wk(yyww: int) -> str:
    y, w = divmod(yyww, 100)
    return f"W{w:02d} '{str(y)[-2:]}"

# ── Simulation ────────────────────────────────────────────────────────────────

def run_simulation(total_ih, se_count, ih_per_se, ramp_wks,
                   start_wk, pre_pct, post_pct, trucks, milestones):
    N = 150
    all_ms_wks = [v for v in milestones.values() if v]
    t_start = min(start_wk, min(all_ms_wks, default=start_wk)) - 4
    weeks = gen_timeline(t_start, N)

    def get_idx(wk):
        return weeks.index(wk) if wk in weeks else -1

    si = get_idx(start_wk)
    if si < 0:
        return None

    full_cap = se_count * ih_per_se
    pre_ih   = total_ih * pre_pct
    post_ih  = total_ih * post_pct
    truck_ih = max(0.0, total_ih - pre_ih - post_ih)

    # Resolve truck indices
    tk_objs = []
    for t in trucks:
        ai, di = get_idx(t["arr"]), get_idx(t["dep"])
        if ai >= 0 and di >= 0 and di >= ai:
            tk_objs.append({**t, "ai": ai, "di": di})

    first_arr = min((t["ai"] for t in tk_objs), default=si + 8)
    last_dep  = max((t["di"] for t in tk_objs), default=si + 20)

    truck_set = set()
    for t in tk_objs:
        truck_set.update(range(t["ai"], t["di"] + 1))
    trk_wk_cnt = max(len(truck_set), 1)

    pre_wks  = max(1, first_arr - si)
    post_wks = max(1, min(30, N - last_dep - 1))

    pool = [0.0] * N
    for i in range(si, min(first_arr, N)):
        pool[i] += pre_ih / pre_wks
    for i in range(N):
        if i in truck_set:
            pool[i] += truck_ih / trk_wk_cnt
    for i in range(last_dep + 1, min(last_dep + 1 + post_wks, N)):
        pool[i] += post_ih / post_wks

    bl, cum = 0.0, 0.0
    rows = []
    for i, wk in enumerate(weeks):
        active = i >= si
        ramp   = min(1.0, (i - si + 1) / max(1, ramp_wks)) if active else 0.0
        cap    = full_cap * ramp
        remaining = max(0.0, total_ih - cum)
        avail  = pool[i] + bl
        sent   = min(avail, cap, remaining + bl)
        bl     = max(0.0, avail - sent)
        cum    = min(total_ih, cum + sent)
        rows.append({
            "idx": i, "wk": wk, "label": fmt_wk(wk),
            "cap": round(cap, 1), "sent": round(sent, 1),
            "bl": round(bl, 1),  "cum": round(cum, 1),
        })

    df = pd.DataFrame(rows)

    ms_status = {}
    for name in ("RG", "SOP", "EG"):
        wk = milestones.get(name)
        if not wk:
            continue
        row = df[df["wk"] == wk]
        if not row.empty:
            done = row.iloc[0]["cum"]
            ms_status[name] = {
                "done": int(round(done)),
                "miss": max(0, int(round(total_ih - done))),
                "pct":  min(1.0, done / total_ih),
                "ok":   done >= total_ih - 0.5,
            }

    done_row = df[df["cum"] >= total_ih]
    completion_wk = int(done_row.iloc[0]["wk"]) if not done_row.empty else None

    return df, ms_status, tk_objs, full_cap, completion_wk

# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.header("Scope & resources")
total_ih  = st.sidebar.number_input("Total IH (scope)", value=1500, step=50, min_value=1)
se_count  = st.sidebar.number_input("SE headcount", value=3.0, step=0.5, min_value=0.5)
ih_per_se = st.sidebar.number_input("IH / SE / week", value=8, step=1, min_value=1)
ramp_wks  = st.sidebar.number_input("Ramp-up weeks", value=4, step=1, min_value=1, max_value=20)

st.sidebar.header("Schedule")
start_wk = st.sidebar.number_input("Work start (YYWW)", value=2535)
pre_pct  = st.sidebar.slider("Pre-work %",  0, 50, 10, step=5,
                              help="IH that can be written before any truck arrives — runs at full SE capacity") / 100
post_pct = st.sidebar.slider("Post-work %", 0, 50, 10, step=5,
                              help="IH remaining after all trucks leave — runs at full SE capacity") / 100

st.sidebar.header("Truck verification windows")
st.sidebar.caption("Trucks define when the physical vehicle is on-site for verification. "
                   "No capacity limit — SEs always work at full rate.")
num_trucks = st.sidebar.number_input("Number of trucks", value=2, min_value=1, max_value=10, step=1)

trucks = []
for i in range(num_trucks):
    with st.sidebar.expander(f"Truck {i + 1}", expanded=True):
        default_arr = 2545 + i * 10
        arr = st.number_input(f"Arrival (YYWW)",   value=default_arr,      key=f"arr_{i}")
        dep = st.number_input(f"Departure (YYWW)",  value=default_arr + 8,  key=f"dep_{i}")
        trucks.append({"id": i + 1, "arr": arr, "dep": dep})

st.sidebar.header("Milestones (YYWW)")
milestones = {
    "FDG":    st.sidebar.number_input("FDG",      value=2532),
    "CBuild": st.sidebar.number_input("C-Build",  value=2548),
    "FIG":    st.sidebar.number_input("FIG",      value=2605),
    "RG":     st.sidebar.number_input("RG",       value=2620),
    "SOP":    st.sidebar.number_input("SOP",      value=2630),
    "EG":     st.sidebar.number_input("EG",       value=2640),
}

# ── Run ───────────────────────────────────────────────────────────────────────

result = run_simulation(
    total_ih, se_count, ih_per_se, ramp_wks,
    start_wk, pre_pct, post_pct, trucks, milestones,
)
if result is None:
    st.error("Work start week not found in timeline. Check your YYWW dates.")
    st.stop()

df, ms_status, tk_objs, full_cap, completion_wk = result

# ── Header ────────────────────────────────────────────────────────────────────

st.title("SE Workpackage Estimation")

completion_str = (
    f"✅ Completes {fmt_wk(completion_wk)}" if completion_wk
    else "❌ Will not complete within the planning window"
)
st.caption(
    f"**{se_count} SE** · **{full_cap} IH/week** at peak · "
    f"**{total_ih:,} total IH** · {completion_str}"
)

# ── Milestone status cards ────────────────────────────────────────────────────

cols = st.columns(3)
gate_labels = {"RG": "RG", "SOP": "SOP", "EG": "EG"}
for col, name in zip(cols, ("RG", "SOP", "EG")):
    s = ms_status.get(name)
    wk_label = fmt_wk(milestones[name])
    with col:
        if s is None:
            st.info(f"**{name}** · {wk_label}\nMilestone not in timeline")
            continue
        icon  = "✅" if s["ok"] else "❌"
        delta = f"-{s['miss']:,} IH short" if s["miss"] > 0 else "On track"
        st.metric(
            label=f"{icon} {name} · {wk_label}",
            value=f"{s['pct'] * 100:.0f}%",
            delta=delta,
            delta_color="normal" if s["ok"] else "inverse",
        )
        st.caption(f"{s['done']:,} / {total_ih:,} IH completed")

st.divider()

# ── Plotly charts ─────────────────────────────────────────────────────────────

MS_COLORS = {
    "FDG":    "rgba(136,135,128,0.7)",
    "CBuild": "rgba(136,135,128,0.7)",
    "FIG":    "rgba(136,135,128,0.7)",
    "RG":     "rgba(186,117,23,1)",
    "SOP":    "rgba(127,119,221,1)",
    "EG":     "rgba(55,138,221,1)",
}
MS_DASH = {"FDG": "dot", "CBuild": "dot", "FIG": "dot",
           "RG": "solid", "SOP": "solid", "EG": "solid"}

tick_mask = df["idx"] % 4 == 0
tick_vals  = df.loc[tick_mask, "idx"].tolist()
tick_texts = df.loc[tick_mask, "label"].tolist()

fig = make_subplots(
    rows=2, cols=1,
    row_heights=[0.62, 0.38],
    shared_xaxes=True,
    vertical_spacing=0.06,
    subplot_titles=("Cumulative progress (burnup)", "Weekly output vs capacity"),
)

# ── Burnup (row 1) ──

# Truck window bands
for t in tk_objs:
    for row in (1, 2):
        fig.add_vrect(
            x0=t["ai"], x1=t["di"],
            fillcolor="rgba(55,138,221,0.07)",
            line_width=0,
            row=row, col=1,
        )

# Scope line
fig.add_hline(
    y=total_ih, line_dash="dash", line_color="rgba(226,75,74,0.7)",
    line_width=1.5, row=1, col=1,
    annotation_text=f"Scope {total_ih:,} IH",
    annotation_position="top right",
    annotation_font_color="rgba(226,75,74,0.9)",
    annotation_font_size=11,
)

# Cumulative area
fig.add_trace(go.Scatter(
    x=df["idx"], y=df["cum"],
    mode="lines",
    name="Cumulative IH",
    line=dict(color="#378ADD", width=2.5),
    fill="tozeroy",
    fillcolor="rgba(55,138,221,0.10)",
    hovertemplate="<b>%{customdata}</b><br>Cumulative: %{y} IH<extra></extra>",
    customdata=df["label"],
), row=1, col=1)

# ── Weekly throughput (row 2) ──

fig.add_trace(go.Bar(
    x=df["idx"], y=df["sent"],
    name="Weekly output",
    marker_color="rgba(55,138,221,0.70)",
    hovertemplate="<b>%{customdata}</b><br>Output: %{y} IH<extra></extra>",
    customdata=df["label"],
), row=2, col=1)

fig.add_trace(go.Scatter(
    x=df["idx"], y=df["cap"],
    mode="lines",
    name="Capacity",
    line=dict(color="#BA7517", width=2, dash="dash"),
    hovertemplate="<b>%{customdata}</b><br>Capacity: %{y} IH<extra></extra>",
    customdata=df["label"],
), row=2, col=1)

# Milestone vertical lines (both charts)
for name, wk in milestones.items():
    ms_df = df[df["wk"] == wk]
    if ms_df.empty:
        continue
    idx = int(ms_df.iloc[0]["idx"])
    color = MS_COLORS.get(name, "gray")
    dash  = MS_DASH.get(name, "dot")
    is_key = name in ("RG", "SOP", "EG")

    for row in (1, 2):
        fig.add_vline(
            x=idx,
            line_color=color,
            line_dash=dash,
            line_width=2 if is_key else 1,
            row=row, col=1,
        )

    # Label only on burnup chart
    y_max = total_ih * 1.05
    fig.add_annotation(
        x=idx, y=y_max,
        text=name,
        showarrow=False,
        font=dict(size=10, color=color.replace(",1)", ",0.9)").replace(",0.7)", ",0.7)")),
        xanchor="left", yanchor="top",
        textangle=0,
        row=1, col=1,
    )

# ── Axes & layout ──

axis_style = dict(
    showgrid=True, gridcolor="rgba(128,128,128,0.12)",
    zeroline=False, showline=False,
    tickfont=dict(size=10, color="#888"),
)

fig.update_xaxes(
    tickvals=tick_vals, ticktext=tick_texts,
    tickangle=-45, tickfont=dict(size=10, color="#888"),
    showgrid=False, zeroline=False, showline=False,
)
fig.update_yaxes(axis_style)
fig.update_yaxes(range=[0, total_ih * 1.08], row=1, col=1)

fig.update_layout(
    height=640,
    margin=dict(t=40, b=20, l=40, r=20),
    legend=dict(
        orientation="h", yanchor="bottom", y=1.01,
        xanchor="left", x=0,
        font=dict(size=11, color="#888"),
        bgcolor="rgba(0,0,0,0)",
    ),
    hovermode="x unified",
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="sans-serif"),
)

st.plotly_chart(fig, use_container_width=True)

# ── Summary table ─────────────────────────────────────────────────────────────

with st.expander("Milestone detail table"):
    rows_out = []
    for name, wk in milestones.items():
        ms_df = df[df["wk"] == wk]
        if ms_df.empty:
            continue
        done = int(ms_df.iloc[0]["cum"])
        miss = max(0, total_ih - done)
        rows_out.append({
            "Milestone": name,
            "Week":      fmt_wk(wk),
            "IH done":   f"{done:,}",
            "IH miss":   f"{miss:,}" if miss > 0 else "—",
            "% done":    f"{min(100, round(done / total_ih * 100))}%",
            "Status":    "✅ On track" if miss == 0 else "❌ Behind",
        })
    st.dataframe(pd.DataFrame(rows_out), use_container_width=True, hide_index=True)
