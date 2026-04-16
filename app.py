import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

st.set_page_config(page_title="SE Workpackage Estimation", layout="wide")

# ── Helpers ───────────────────────────────────────────────────────────────────

def next_week(yyww: int) -> int:
    y, w = divmod(yyww, 100)
    return (y + 1) * 100 + 1 if w >= 52 else y * 100 + (w + 1)

def gen_timeline(start: int, n: int) -> list:
    weeks = [start]
    for _ in range(n - 1):
        weeks.append(next_week(weeks[-1]))
    return weeks

def fmt_wk(yyww: int) -> str:
    y, w = divmod(yyww, 100)
    return f"W{w:02d}'{str(y)[-2:]}"

# ── Simulation ────────────────────────────────────────────────────────────────

def run_simulation(total_ih, se_count, ih_per_se, ramp_wks,
                   start_wk, pre_pct, post_pct, trucks, milestones):
    N = 150
    all_ms = [v for v in milestones.values() if v]
    t_start = min(start_wk, min(all_ms, default=start_wk)) - 4
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
        ramp  = min(1.0, (i - si + 1) / max(1, ramp_wks)) if i >= si else 0.0
        cap   = full_cap * ramp
        avail = pool[i] + bl
        sent  = min(avail, cap, max(0.0, total_ih - cum) + bl)
        bl    = max(0.0, avail - sent)
        cum   = min(total_ih, cum + sent)
        rows.append({"idx": i, "wk": wk, "cap": cap, "sent": sent, "cum": cum})

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
    help="IH writable before any truck arrives — runs at full SE capacity") / 100
post_pct = st.sidebar.slider("Post-work %", 0, 50, 10, step=5,
    help="IH remaining after all trucks leave — runs at full SE capacity") / 100

st.sidebar.header("Truck verification windows")
st.sidebar.caption("Trucks define when the physical vehicle is on-site. "
                   "No capacity limit — SEs always work at full rate.")
num_trucks = st.sidebar.number_input("Number of trucks", value=2, min_value=1, max_value=10, step=1)

trucks = []
for i in range(num_trucks):
    with st.sidebar.expander(f"Truck {i + 1}", expanded=True):
        default_arr = 2545 + i * 10
        arr = st.number_input("Arrival (YYWW)",   value=default_arr,     key=f"arr_{i}")
        dep = st.number_input("Departure (YYWW)", value=default_arr + 8, key=f"dep_{i}")
        trucks.append({"id": i + 1, "arr": int(arr), "dep": int(dep)})

st.sidebar.header("Milestones (YYWW)")
milestones = {
    "FDG":    int(st.sidebar.number_input("FDG",     value=2532)),
    "CBuild": int(st.sidebar.number_input("C-Build", value=2548)),
    "FIG":    int(st.sidebar.number_input("FIG",     value=2605)),
    "RG":     int(st.sidebar.number_input("RG",      value=2620)),
    "SOP":    int(st.sidebar.number_input("SOP",     value=2630)),
    "EG":     int(st.sidebar.number_input("EG",      value=2640)),
}

# ── Run ───────────────────────────────────────────────────────────────────────

result = run_simulation(total_ih, se_count, ih_per_se, ramp_wks,
                        start_wk, pre_pct, post_pct, trucks, milestones)
if result is None:
    st.error("Work start week not found in timeline. Check your YYWW dates.")
    st.stop()

df, ms_status, tk_objs, full_cap, completion_wk = result

# ── Header ────────────────────────────────────────────────────────────────────

st.title("SE Workpackage Estimation")
if completion_wk:
    st.caption(f"**{se_count} SE** · **{full_cap} IH/week** at peak · "
               f"**{total_ih:,} total IH** · ✅ Completes {fmt_wk(completion_wk)}")
else:
    st.caption(f"**{se_count} SE** · **{full_cap} IH/week** at peak · "
               f"**{total_ih:,} total IH** · ❌ Will not complete within planning window")

# ── Milestone status cards ────────────────────────────────────────────────────

cols = st.columns(3)
for col, name in zip(cols, ("RG", "SOP", "EG")):
    s = ms_status.get(name)
    wk_label = fmt_wk(milestones[name])
    with col:
        if s is None:
            st.info(f"**{name}** · {wk_label} — not in timeline")
            continue
        delta = f"-{s['miss']:,} IH short" if s["miss"] > 0 else "On track"
        icon  = "✅" if s["ok"] else "❌"
        st.metric(
            label=f"{icon} {name} · {wk_label}",
            value=f"{s['pct'] * 100:.0f}%",
            delta=delta,
            delta_color="normal" if s["ok"] else "inverse",
        )
        st.caption(f"{s['done']:,} / {total_ih:,} IH completed")

st.divider()

# ── Chart constants ───────────────────────────────────────────────────────────

CLR_BURNUP   = "#378ADD"
CLR_CAPACITY = "#BA7517"
CLR_SCOPE    = "#E24B4A"
CLR_TRUCK    = "#378ADD"
CLR_GRID     = "#ebebeb"
MS_COLORS    = {
    "FDG": "#AAAAAA", "CBuild": "#AAAAAA", "FIG": "#AAAAAA",
    "RG":  "#BA7517", "SOP":    "#7F77DD", "EG":  "#378ADD",
}

tick_df   = df[df["idx"] % 4 == 0]
tick_pos  = tick_df["idx"].tolist()
tick_lbls = [fmt_wk(int(w)) for w in tick_df["wk"]]

def ms_idx(name):
    row = df[df["wk"] == milestones[name]]
    return int(row.iloc[0]["idx"]) if not row.empty else None

# ── Figure ────────────────────────────────────────────────────────────────────

fig, (ax1, ax2) = plt.subplots(
    2, 1, figsize=(16, 9),
    gridspec_kw={"height_ratios": [3, 2]},
    sharex=True,
)
fig.patch.set_facecolor("white")

for ax in (ax1, ax2):
    ax.set_facecolor("white")
    ax.grid(axis="y", color=CLR_GRID, linewidth=0.6, zorder=0)
    ax.spines[["top", "right", "left", "bottom"]].set_visible(False)
    ax.tick_params(left=False, bottom=False, labelcolor="#666")

# Truck on-site bands
for t in tk_objs:
    for ax in (ax1, ax2):
        ax.axvspan(t["ai"], t["di"], color=CLR_TRUCK, alpha=0.07, zorder=1)

# ── Burnup (ax1) ──────────────────────────────────────────────────────────────

ax1.axhline(total_ih, color=CLR_SCOPE, linewidth=1.5, linestyle="--", zorder=2)
ax1.text(df["idx"].max() + 0.5, total_ih, f"Scope {total_ih:,}",
         va="center", ha="left", fontsize=9, color=CLR_SCOPE)

ax1.fill_between(df["idx"], df["cum"], alpha=0.10, color=CLR_BURNUP, zorder=2)
ax1.plot(df["idx"], df["cum"], color=CLR_BURNUP, linewidth=2.5, zorder=3)

ax1.set_ylim(0, total_ih * 1.12)
ax1.set_ylabel("Cumulative IH", fontsize=10, color="#666", labelpad=8)
ax1.set_title("Cumulative progress (burnup)", fontsize=11, color="#444",
              fontweight="normal", loc="left", pad=10)

# ── Weekly throughput (ax2) ───────────────────────────────────────────────────

ax2.bar(df["idx"], df["sent"], color=CLR_BURNUP, alpha=0.70, zorder=2, width=0.85)
ax2.plot(df["idx"], df["cap"], color=CLR_CAPACITY, linewidth=2,
         linestyle="--", zorder=3)
ax2.set_ylabel("IH / week", fontsize=10, color="#666", labelpad=8)
ax2.set_title("Weekly output vs capacity", fontsize=11, color="#444",
              fontweight="normal", loc="left", pad=10)

# ── Milestone lines ───────────────────────────────────────────────────────────

for name, wk in milestones.items():
    idx = ms_idx(name)
    if idx is None:
        continue
    color = MS_COLORS.get(name, "#999")
    lw    = 1.8 if name in ("RG", "SOP", "EG") else 1.0
    ls    = "-" if name in ("RG", "SOP", "EG") else (0, (4, 4))
    for ax in (ax1, ax2):
        ax.axvline(idx, color=color, linewidth=lw, linestyle=ls, zorder=4, alpha=0.9)
    ax1.text(idx + 0.4, total_ih * 1.06, name,
             fontsize=9, color=color, va="top", ha="left")

# ── Status annotations on burnup ─────────────────────────────────────────────

for name in ("RG", "SOP", "EG"):
    s = ms_status.get(name)
    if not s:
        continue
    idx   = ms_idx(name)
    color = MS_COLORS[name]
    bg    = "#e8f5e9" if s["ok"] else "#ffebee"
    fc    = "#2e7d32" if s["ok"] else "#c62828"
    label = f"{s['pct']*100:.0f}%  {s['done']:,} IH"
    if not s["ok"]:
        label += f"\n−{s['miss']:,} IH short"
    ax1.annotate(
        label,
        xy=(idx, s["done"]),
        xytext=(idx + 2.5, max(s["done"] - total_ih * 0.14, total_ih * 0.05)),
        fontsize=8.5, color=fc, ha="left", va="center",
        bbox=dict(boxstyle="round,pad=0.4", fc=bg, ec=color, lw=0.9),
        arrowprops=dict(arrowstyle="-", color=color, lw=0.8),
    )

# ── X axis ────────────────────────────────────────────────────────────────────

ax2.set_xticks(tick_pos)
ax2.set_xticklabels(tick_lbls, rotation=55, ha="right", fontsize=9)
ax2.set_xlim(df["idx"].min() - 1, df["idx"].max() + 4)

# ── Legend ────────────────────────────────────────────────────────────────────

legend_handles = [
    Line2D([0], [0], color=CLR_BURNUP,   linewidth=2.5,             label="Cumulative IH"),
    Line2D([0], [0], color=CLR_SCOPE,    linewidth=1.5, ls="--",    label=f"Scope ({total_ih:,})"),
    Line2D([0], [0], color=CLR_CAPACITY, linewidth=2,   ls="--",    label="Capacity"),
    mpatches.Patch(facecolor=CLR_BURNUP, alpha=0.15,                label="Truck on-site"),
    Line2D([0], [0], color=MS_COLORS["RG"],  linewidth=1.8,         label="RG"),
    Line2D([0], [0], color=MS_COLORS["SOP"], linewidth=1.8,         label="SOP"),
    Line2D([0], [0], color=MS_COLORS["EG"],  linewidth=1.8,         label="EG"),
]
ax1.legend(handles=legend_handles, loc="upper left", fontsize=9,
           framealpha=0.9, edgecolor="#ddd", ncol=4, handlelength=1.8)

plt.tight_layout(rect=[0, 0, 0.97, 1])
st.pyplot(fig)
plt.close(fig)

# ── Detail table ──────────────────────────────────────────────────────────────

with st.expander("Milestone detail table"):
    table_rows = []
    for name, wk in milestones.items():
        row = df[df["wk"] == wk]
        if row.empty:
            continue
        done = int(row.iloc[0]["cum"])
        miss = max(0, total_ih - done)
        table_rows.append({
            "Milestone": name,
            "Week":      fmt_wk(wk),
            "IH done":   f"{done:,}",
            "IH miss":   f"{miss:,}" if miss > 0 else "—",
            "% done":    f"{min(100, round(done / total_ih * 100))}%",
            "Status":    "✅ On track" if miss == 0 else "❌ Behind",
        })
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
