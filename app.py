import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

st.set_page_config(page_title="SE Workpackage Estimation", layout="wide")

# ── Helpers ───────────────────────────────────────────────────────────────────

def next_week(yyww):
    y, w = divmod(yyww, 100)
    return (y + 1) * 100 + 1 if w >= 52 else y * 100 + (w + 1)

def gen_timeline(start, n):
    weeks = [start]
    for _ in range(n - 1):
        weeks.append(next_week(weeks[-1]))
    return weeks

def fmt_wk(yyww):
    y, w = divmod(yyww, 100)
    return f"W{w:02d}'{str(y)[-2:]}"

# ── Simulation ────────────────────────────────────────────────────────────────
#
# Model:
#   IH is ALWAYS available — the only constraint is SE capacity.
#   Capacity shape:
#     • Pre-work phase  : ramps up linearly to full_cap over ramp_wks
#     • Each truck window: Hann bell (0 → full_cap → 0), peaking mid-window
#         UNLESS remaining IH cannot reach next milestone → forced to full_cap
#     • Post-work phase : ramps up linearly to full_cap over ramp_wks
#     • Gaps between trucks: zero capacity (SEs not active)
#
# ─────────────────────────────────────────────────────────────────────────────

def run_simulation(total_ih, se_count, ih_per_se, ramp_wks,
                   start_wk, pre_pct, post_pct, trucks, milestones):
    N = 160
    all_ms = [v for v in milestones.values() if v]
    t_start = min(start_wk, min(all_ms, default=start_wk)) - 4
    weeks = gen_timeline(t_start, N)

    def get_idx(wk):
        return weeks.index(wk) if wk in weeks else -1

    si = get_idx(start_wk)
    if si < 0:
        return None

    full_cap = se_count * ih_per_se

    # Phase IH budgets
    pre_ih   = total_ih * pre_pct
    post_ih  = total_ih * post_pct
    truck_ih = max(0.0, total_ih - pre_ih - post_ih)

    # Resolve truck indices
    tk_objs = []
    for t in trucks:
        ai, di = get_idx(t["arr"]), get_idx(t["dep"])
        if ai >= 0 and di >= 0 and di >= ai:
            tk_objs.append({**t, "ai": ai, "di": di})

    first_arr    = min((t["ai"] for t in tk_objs), default=si + 8)
    last_dep     = max((t["di"] for t in tk_objs), default=si + 20)
    n_trucks     = max(len(tk_objs), 1)
    ih_per_truck = truck_ih / n_trucks

    post_start = last_dep + 1
    post_end   = min(last_dep + max(1, min(30, N - last_dep - 1)), N - 1)

    # Gate indices in order
    gate_names = ["RG", "SOP", "EG"]
    gate_idxs  = []
    for gn in gate_names:
        gi = get_idx(milestones.get(gn, 0))
        if gi >= 0:
            gate_idxs.append(gi)

    # Phase IH tracking
    pre_rem   = pre_ih
    truck_rem = {t["id"]: ih_per_truck for t in tk_objs}
    post_rem  = post_ih

    cum  = 0.0
    rows = []

    for i, wk in enumerate(weeks):
        remaining = max(0.0, total_ih - cum)

        # ── Which phase? ──────────────────────────────────────────────────────
        in_pre   = si <= i < first_arr
        in_post  = post_start <= i <= post_end
        truck_t  = next((t for t in tk_objs if t["ai"] <= i <= t["di"]), None)

        # ── Available IH this week (phase-limited) ────────────────────────────
        if in_pre:
            phase_avail = max(0.0, pre_rem)
        elif truck_t is not None:
            phase_avail = max(0.0, truck_rem[truck_t["id"]])
        elif in_post:
            phase_avail = max(0.0, post_rem)
        else:
            phase_avail = 0.0   # gap / before start

        # ── Capacity shape ────────────────────────────────────────────────────
        if truck_t is not None:
            ai, di = truck_t["ai"], truck_t["di"]
            span   = max(di - ai, 1)
            # Hann window: smooth bell peaking at centre of truck window
            hann_factor = 0.5 * (1.0 - np.cos(np.pi * (i - ai) / span))
            natural_cap = full_cap * hann_factor

            # Override: if remaining IH can't reach the nearest upcoming gate
            # at the NATURAL (reduced) pace, force full_cap so we don't fall behind
            override = False
            for gi in sorted(gate_idxs):
                if gi <= i:
                    continue
                wks_to_gate = gi - i
                if wks_to_gate > 0 and remaining >= natural_cap * wks_to_gate:
                    override = True   # natural cap too slow → stay at full
                break

            effective_cap = full_cap if override else natural_cap

        elif in_pre:
            phase_start  = si
            weeks_in      = i - phase_start
            effective_cap = full_cap * min(1.0, (weeks_in + 1) / max(1, ramp_wks))

        elif in_post:
            weeks_in      = i - post_start
            effective_cap = full_cap * min(1.0, (weeks_in + 1) / max(1, ramp_wks))

        else:
            effective_cap = 0.0

        # ── Process IH ───────────────────────────────────────────────────────
        sent = min(phase_avail, effective_cap, remaining)
        cum  = min(total_ih, cum + sent)

        # Deduct from phase budget
        if in_pre:
            pre_rem -= sent
        elif truck_t is not None:
            truck_rem[truck_t["id"]] -= sent
        elif in_post:
            post_rem -= sent

        rows.append({
            "idx":  i,   "wk": wk,
            "cap":  round(effective_cap, 3),
            "fcap": round(full_cap,      3),
            "sent": round(sent,          3),
            "cum":  round(cum,           3),
        })

    df = pd.DataFrame(rows)

    ms_status = {}
    for name in gate_names:
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

    done_row      = df[df["cum"] >= total_ih]
    completion_wk = int(done_row.iloc[0]["wk"]) if not done_row.empty else None

    return df, ms_status, tk_objs, full_cap, completion_wk

# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.header("Scope & resources")
total_ih  = st.sidebar.number_input("Total IH (scope)", value=1500, step=50,  min_value=1)
se_count  = st.sidebar.number_input("SE headcount",      value=3.0,  step=0.5, min_value=0.5)
ih_per_se = st.sidebar.number_input("IH / SE / week",    value=8,    step=1,   min_value=1)
ramp_wks  = st.sidebar.number_input("Ramp-up weeks",     value=4,    step=1,   min_value=1, max_value=20)

st.sidebar.header("Schedule")
start_wk = st.sidebar.number_input(
    "Work start week (YYWW)", value=2535,
    help="Week SEs start sending IH to publishing. Start of pre-work phase.",
)
pre_pct  = st.sidebar.slider("Pre-work %",  0, 50, 10, step=5,
    help="% of total IH that can be sent before any truck arrives") / 100
post_pct = st.sidebar.slider("Post-work %", 0, 50, 10, step=5,
    help="% of total IH sendable after all trucks leave") / 100

st.sidebar.header("Truck verification windows")
st.sidebar.caption(
    "SE output follows a bell curve (Hann window) per truck window — "
    "ramping up on arrival, peaking mid-window, ramping down before departure. "
    "Bell ramp-down is suppressed if a milestone is at risk."
)
num_trucks = st.sidebar.number_input("Number of trucks", value=2, min_value=1, max_value=10, step=1)

trucks = []
for i in range(int(num_trucks)):
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
all_ok = all(s.get("ok", False) for s in ms_status.values())

if completion_wk:
    extra = "  — more SEs moves completion earlier" if all_ok else ""
    st.caption(
        f"**{se_count} SE** · **{full_cap} IH/week** peak · **{total_ih:,} total IH** "
        f"· Completes **{fmt_wk(completion_wk)}**{extra}"
    )
else:
    st.caption(
        f"**{se_count} SE** · **{full_cap} IH/week** peak · **{total_ih:,} total IH** "
        "· ❌ Will not complete in planning window"
    )

cols = st.columns(3)
for col, name in zip(cols, ("RG", "SOP", "EG")):
    s      = ms_status.get(name)
    wk_lbl = fmt_wk(milestones[name])
    with col:
        if s is None:
            st.info(f"**{name}** · {wk_lbl} — not in timeline")
            continue
        delta = f"-{s['miss']:,} IH short" if s["miss"] > 0 else "On track"
        icon  = "✅" if s["ok"] else "❌"
        st.metric(label=f"{icon} {name} · {wk_lbl}", value=f"{s['pct']*100:.0f}%",
                  delta=delta, delta_color="normal" if s["ok"] else "inverse")
        st.caption(f"{s['done']:,} / {total_ih:,} IH")

st.divider()

# ── Chart constants ───────────────────────────────────────────────────────────

CLR_BARS     = "#378ADD"
CLR_CAP      = "#BA7517"
CLR_FCAP     = "#deb96a"
CLR_CUM      = "#1a3a5c"
CLR_SCOPE    = "#E24B4A"
CLR_WSTART   = "#7755AA"
CLR_COMP     = "#22a855"
CLR_GRID     = "#ebebeb"
MS_COLORS    = {
    "FDG": "#AA44AA", "CBuild": "#CC8800", "FIG": "#CC3322",
    "RG":  "#444444", "SOP":    "#1144CC", "EG":  "#228B22",
}
TRUCK_COLORS = ["#1f77b4","#ff7f0e","#2ca02c","#d62728",
                "#9467bd","#8c564b","#e377c2","#17becf"]

xs        = df["idx"].to_numpy()
tick_df   = df[df["idx"] % 4 == 0]
tick_pos  = tick_df["idx"].tolist()
tick_lbls = [str(int(w)) for w in tick_df["wk"]]

def ms_idx(name):
    row = df[df["wk"] == milestones.get(name, 0)]
    return int(row.iloc[0]["idx"]) if not row.empty else None

def get_cum_at(name):
    wk  = milestones.get(name)
    row = df[df["wk"] == wk] if wk else pd.DataFrame()
    return float(row.iloc[0]["cum"]) if not row.empty else 0.0

# Smooth bell for each truck (for visual overlay, 20× resolution)
def smooth_bell(ai, di, full_c, n):
    span = max(di - ai, 1)
    fine = np.linspace(ai, di, span * 20)
    hann = 0.5 * (1.0 - np.cos(np.pi * (fine - ai) / span))
    return fine, full_c * hann

# Scale
weekly_max = max(df["cap"].max(), df["sent"].max(), full_cap) * 1.15
weekly_max = max(weekly_max, 1.0)
ARROW_Y    = [weekly_max * 1.22, weekly_max * 1.14, weekly_max * 1.06]
EXT_YLIM   = weekly_max * 1.42

si_row = df[df["wk"] == start_wk]["idx"]
si_x   = int(si_row.iloc[0]) if not si_row.empty else None

# ── Single figure with dual y-axis ───────────────────────────────────────────

fig, ax = plt.subplots(figsize=(20, 11))
ax2 = ax.twinx()          # right axis: cumulative IH (burnup)

fig.patch.set_facecolor("white")
for a in (ax, ax2):
    a.set_facecolor("white")
    a.spines[["top", "left", "bottom"]].set_visible(False)
    a.tick_params(left=False, bottom=False)

ax.spines["right"].set_visible(False)
ax.grid(axis="y", color=CLR_GRID, linewidth=0.6, zorder=0)

# ── Truck bands ───────────────────────────────────────────────────────────────

for t in tk_objs:
    ax.axvspan(t["ai"], t["di"], color=CLR_BARS, alpha=0.06, zorder=1)

# ── Weekly bars (sent IH) ─────────────────────────────────────────────────────

ax.bar(xs, df["sent"].to_numpy(), color=CLR_BARS, alpha=0.75,
       zorder=2, width=0.85, label="Weekly output (sent IH)")

# ── Bell curves per truck (capacity shape) ────────────────────────────────────

bell_handles = []
for i, t in enumerate(tk_objs):
    tc         = TRUCK_COLORS[i % len(TRUCK_COLORS)]
    fine_x, fy = smooth_bell(t["ai"], t["di"], full_cap, len(df))
    ax.fill_between(fine_x, fy, alpha=0.15, color=tc, zorder=2)
    ax.plot(fine_x, fy, color=tc, lw=2.2, zorder=3, alpha=0.85,
            ls="--", label=f"T{t['id']} natural bell capacity")
    bell_handles.append(Line2D([0],[0], color=tc, lw=2, ls="--",
                               label=f"T{t['id']} bell capacity"))

# ── Effective capacity (actual — may diverge from bell if milestone at risk) ──

ax.plot(xs, df["cap"].to_numpy(), color=CLR_CAP, lw=2.2, ls="-.",
        zorder=4, alpha=0.95, label="Effective capacity (override if behind)")

# ── Max SE reference line ─────────────────────────────────────────────────────

ax.axhline(full_cap, color=CLR_FCAP, lw=1.2, ls=":",
           zorder=2, alpha=0.70, label=f"Max SE capacity ({full_cap} IH/wk)")

# ── Separator: data zone vs annotation zone ───────────────────────────────────

ax.axhline(weekly_max, color="#cccccc", lw=0.5, zorder=1)
ax.set_ylim(0, EXT_YLIM)

# ── Work start ────────────────────────────────────────────────────────────────

if si_x is not None:
    ax.axvline(si_x, color=CLR_WSTART, lw=2, ls="--", zorder=5, alpha=0.85)
    ax.text(si_x - 0.5, weekly_max * 0.90,
            f"Work Start\n{fmt_wk(start_wk)}",
            fontsize=8.5, color=CLR_WSTART, va="top", ha="right",
            bbox=dict(boxstyle="round,pad=0.3", fc="white",
                      ec=CLR_WSTART, lw=0.8, alpha=0.92))

# ── Truck Arr / Dep labels ────────────────────────────────────────────────────

for i, t in enumerate(tk_objs):
    tc  = TRUCK_COLORS[i % len(TRUCK_COLORS)]
    off = i * 0.055
    ax.axvline(t["ai"], color=tc, lw=1.3, ls="--", zorder=5, alpha=0.80)
    ax.text(t["ai"] + 0.3, weekly_max * (0.92 - off),
            f"T{t['id']} Arr", fontsize=8.5, color=tc,
            va="top", ha="left", fontweight="bold")
    ax.axvline(t["di"], color=tc, lw=1.3, ls=":", zorder=5, alpha=0.80)
    ax.text(t["di"] + 0.3, weekly_max * (0.83 - off),
            f"T{t['id']} Dep", fontsize=8.5, color=tc,
            va="top", ha="left", fontweight="bold")

# ── Milestone verticals ───────────────────────────────────────────────────────

for name, wk in milestones.items():
    idx = ms_idx(name)
    if idx is None:
        continue
    color  = MS_COLORS.get(name, "#999")
    is_key = name in ("RG", "SOP", "EG")
    ax.axvline(idx, color=color,
               lw=2.0 if is_key else 1.0,
               ls="-" if is_key else (0, (4, 4)),
               zorder=4, alpha=0.90)
    ax.text(idx + 0.2, weekly_max * 0.97, name,
            fontsize=9, color=color, rotation=90, va="top", ha="left",
            fontweight="bold" if is_key else "normal")

# ── Status boxes ─────────────────────────────────────────────────────────────

BOX_Y = {"RG": 0.70, "SOP": 0.52, "EG": 0.34}
for name in ("RG", "SOP", "EG"):
    s = ms_status.get(name)
    if not s:
        continue
    idx   = ms_idx(name)
    color = MS_COLORS[name]
    bg    = "#e8f5e9" if s["ok"] else "#ffebee"
    fc    = "#2e7d32" if s["ok"] else "#c62828"
    label = f"{name} Status\nSent: {s['done']:,}\nMissed: {s['miss']:,}"
    ax.annotate(
        label,
        xy=(idx, weekly_max * 0.04),
        xytext=(idx + 2.5, weekly_max * BOX_Y.get(name, 0.50)),
        fontsize=9, color=fc, ha="left", va="center", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.5", fc=bg, ec=color, lw=1.8),
        arrowprops=dict(arrowstyle="-|>", color=color, lw=1.4,
                        connectionstyle="arc3,rad=0.1"),
        annotation_clip=False,
    )

# ── Dimension arrows FIG→RG, RG→SOP, SOP→EG ─────────────────────────────────

DIM_PAIRS = [("FIG","RG",ARROW_Y[0]), ("RG","SOP",ARROW_Y[1]), ("SOP","EG",ARROW_Y[2])]
for ms1, ms2, arr_y in DIM_PAIRS:
    x1 = ms_idx(ms1)
    x2 = ms_idx(ms2)
    if x1 is None or x2 is None or x1 >= x2:
        continue
    ih_diff = max(0.0, get_cum_at(ms2) - get_cum_at(ms1))
    for xv in (x1, x2):
        ax.plot([xv, xv], [weekly_max, arr_y], color="#aaaaaa",
                lw=0.7, ls=":", zorder=1)
    ax.annotate("", xy=(x2, arr_y), xytext=(x1, arr_y),
                arrowprops=dict(arrowstyle="<->", color="#333",
                                lw=1.6, mutation_scale=13),
                annotation_clip=False)
    ax.text((x1+x2)/2, arr_y + weekly_max*0.025,
            f"{int(round(ih_diff))} IH",
            ha="center", va="bottom", fontsize=10,
            fontweight="bold", color="#111", clip_on=False)

# ═══════════════════════════════════════════════════════════════════════════════
# AX2  —  BURNUP (right axis)
# ═══════════════════════════════════════════════════════════════════════════════

cum_arr = df["cum"].to_numpy()
ax2.fill_between(xs, cum_arr, alpha=0.07, color=CLR_CUM, zorder=2)
ax2.plot(xs, cum_arr, color=CLR_CUM, lw=2.8, zorder=5,
         label="Cumulative IH (burnup)")

ax2.axhline(total_ih, color=CLR_SCOPE, lw=1.5, ls="--", zorder=3)
ax2.text(df["idx"].max() + 0.5, total_ih, f"Scope {total_ih:,}",
         va="center", ha="left", fontsize=9, color=CLR_SCOPE)

# Milestone annotations on burnup
B_Y = {"RG": 0.55, "SOP": 0.38, "EG": 0.22}
for name in ("RG", "SOP", "EG"):
    s = ms_status.get(name)
    if not s:
        continue
    idx      = ms_idx(name)
    color    = MS_COLORS[name]
    bg       = "#e8f5e9" if s["ok"] else "#ffebee"
    fc       = "#2e7d32" if s["ok"] else "#c62828"
    miss_str = "On track" if s["ok"] else f"Miss {s['miss']:,}"
    label    = f"{name}: {s['done']:,}/{total_ih:,}\n{miss_str}"
    ax2.annotate(
        label,
        xy=(idx, s["done"]),
        xytext=(idx - 4, total_ih * B_Y.get(name, 0.4)),
        fontsize=8, color=fc, ha="right", va="center",
        bbox=dict(boxstyle="round,pad=0.35", fc=bg, ec=color, lw=1.0),
        arrowprops=dict(arrowstyle="-|>", color=color, lw=0.9),
        annotation_clip=False,
    )

# Completion
if completion_wk:
    comp_row = df[df["wk"] == completion_wk]
    if not comp_row.empty:
        cidx = int(comp_row.iloc[0]["idx"])
        ax2.axvline(cidx, color=CLR_COMP, lw=2, zorder=6, alpha=0.85)
        ax2.text(cidx + 0.4, total_ih * 0.12,
                 f"Done\n{fmt_wk(completion_wk)}",
                 fontsize=8.5, color=CLR_COMP, va="center", ha="left",
                 bbox=dict(boxstyle="round,pad=0.3", fc="#e6f9ee",
                           ec=CLR_COMP, lw=0.8))

ax2.set_ylim(0, total_ih * 1.18)
ax2.set_ylabel("Cumulative IH  (burnup)", fontsize=10, color=CLR_CUM,
               labelpad=10)
ax2.tick_params(axis="y", labelcolor=CLR_CUM)
ax2.spines["right"].set_visible(True)
ax2.spines["right"].set_color("#cccccc")
ax2.spines["right"].set_linewidth(0.5)

# ── Axes final ────────────────────────────────────────────────────────────────

ax.set_xticks(tick_pos)
ax.set_xticklabels(tick_lbls, rotation=60, ha="right", fontsize=9)
ax.set_xlim(df["idx"].min() - 1, df["idx"].max() + 5)
ax.set_ylabel("Infoheaders / week  (left)", fontsize=10, color="#555", labelpad=8)
ax.tick_params(axis="y", labelcolor="#666")
ax.set_title(
    "SE Workpackage  ·  weekly output + cumulative burnup",
    fontsize=12, color="#333", fontweight="normal", loc="left", pad=10,
)

# ── Combined legend ───────────────────────────────────────────────────────────

legend_handles = (
    bell_handles
    + [
        mpatches.Patch(facecolor=CLR_BARS,  alpha=0.75, label="Weekly output (sent IH)"),
        Line2D([0],[0], color=CLR_CAP,   lw=2.2, ls="-.",  label="Effective capacity"),
        Line2D([0],[0], color=CLR_FCAP,  lw=1.2, ls=":",   label=f"Max SE cap ({full_cap}/wk)"),
        Line2D([0],[0], color=CLR_CUM,   lw=2.8,           label="Cumulative IH (right axis)"),
        Line2D([0],[0], color=CLR_SCOPE, lw=1.5, ls="--",  label=f"Scope ({total_ih:,})"),
        Line2D([0],[0], color=CLR_WSTART,lw=1.8, ls="--",  label="Work start"),
    ]
)
ax.legend(handles=legend_handles, loc="upper left", fontsize=8.5,
          framealpha=0.92, edgecolor="#ddd", ncol=3)

plt.tight_layout()
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
