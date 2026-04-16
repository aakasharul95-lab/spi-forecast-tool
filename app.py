import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

st.set_page_config(page_title="SE Workpackage Estimation", layout="wide")

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
        ramp      = min(1.0, (i - si + 1) / max(1, ramp_wks)) if i >= si else 0.0
        cap       = full_cap * ramp
        remaining = max(0.0, total_ih - cum)
        avail     = pool[i] + bl
        sent      = min(avail, cap, remaining)
        bl        = max(0.0, avail - sent)
        cum       = min(total_ih, cum + sent)
        rows.append({"idx": i, "wk": wk, "cap": round(cap, 2), "pool": round(pool[i], 2),
                     "sent": round(sent, 2), "bl": round(bl, 2), "cum": round(cum, 2)})
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

st.sidebar.header("Scope & resources")
total_ih  = st.sidebar.number_input("Total IH (scope)", value=1500, step=50,  min_value=1)
se_count  = st.sidebar.number_input("SE headcount",      value=3.0,  step=0.5, min_value=0.5)
ih_per_se = st.sidebar.number_input("IH / SE / week",    value=8,    step=1,   min_value=1)
ramp_wks  = st.sidebar.number_input("Ramp-up weeks",     value=4,    step=1,   min_value=1, max_value=20)
st.sidebar.header("Schedule")
start_wk = st.sidebar.number_input("Work start (YYWW)", value=2535)
pre_pct  = st.sidebar.slider("Pre-work %",  0, 50, 10, step=5) / 100
post_pct = st.sidebar.slider("Post-work %", 0, 50, 10, step=5) / 100
st.sidebar.header("Truck verification windows")
st.sidebar.caption("Physical truck presence for verification only. No SE capacity limit.")
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

result = run_simulation(total_ih, se_count, ih_per_se, ramp_wks,
                        start_wk, pre_pct, post_pct, trucks, milestones)
if result is None:
    st.error("Work start week not found in timeline. Check your YYWW dates.")
    st.stop()
df, ms_status, tk_objs, full_cap, completion_wk = result

st.title("SE Workpackage Estimation")
all_ok = all(s.get("ok", False) for s in ms_status.values())
if completion_wk:
    extra = " — increasing SE moves completion earlier without changing pass/fail" if all_ok else ""
    st.caption(f"**{se_count} SE** · **{full_cap} IH/week** at peak · **{total_ih:,} total IH** · Completes **{fmt_wk(completion_wk)}**" + extra)
else:
    st.caption(f"**{se_count} SE** · **{full_cap} IH/week** at peak · **{total_ih:,} total IH** · Will not complete in planning window")

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

if all_ok and completion_wk:
    st.info("All milestones on track. More SEs moves the completion date earlier — watch the green marker shift left on the chart.")

st.divider()

CLR_BURNUP   = "#378ADD"
CLR_WORK_GEN = "#222222"
CLR_CAPACITY = "#BA7517"
CLR_SCOPE    = "#E24B4A"
CLR_WSTART   = "#7755AA"
CLR_GRID     = "#ebebeb"
CLR_COMP     = "#22a855"
MS_COLORS = {
    "FDG": "#AA44AA", "CBuild": "#CC8800", "FIG": "#CC3322",
    "RG":  "#444444", "SOP":    "#1144CC", "EG":  "#228B22",
}
TRUCK_COLORS = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b","#e377c2","#17becf"]

tick_df   = df[df["idx"] % 4 == 0]
tick_pos  = tick_df["idx"].tolist()
tick_lbls = [str(int(w)) for w in tick_df["wk"]]

def ms_idx(name):
    row = df[df["wk"] == milestones.get(name, 0)]
    return int(row.iloc[0]["idx"]) if not row.empty else None

def get_cum_at(name):
    wk = milestones.get(name)
    if not wk:
        return 0.0
    row = df[df["wk"] == wk]
    return float(row.iloc[0]["cum"]) if not row.empty else 0.0

max_y    = max(df["pool"].max(), df["cap"].max(), df["sent"].max()) * 1.1
max_y    = max(max_y, 1.0)
ARROW_Y  = [max_y * 1.22, max_y * 1.14, max_y * 1.06]
EXT_YLIM = max_y * 1.42
si_row   = df[df["wk"] == start_wk]["idx"]
si_x     = int(si_row.iloc[0]) if not si_row.empty else None

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(19, 13),
    gridspec_kw={"height_ratios": [2.2, 3.8]}, sharex=True)
fig.patch.set_facecolor("white")
for ax in (ax1, ax2):
    ax.set_facecolor("white")
    ax.grid(axis="y", color=CLR_GRID, linewidth=0.6, zorder=0)
    ax.spines[["top","right","left","bottom"]].set_visible(False)
    ax.tick_params(left=False, bottom=False, labelcolor="#555")
for t in tk_objs:
    for ax in (ax1, ax2):
        ax.axvspan(t["ai"], t["di"], color=CLR_BURNUP, alpha=0.07, zorder=1)

ax1.axhline(total_ih, color=CLR_SCOPE, lw=1.5, ls="--", zorder=2)
ax1.text(df["idx"].max() + 0.5, total_ih, f"Scope  {total_ih:,}", va="center", ha="left", fontsize=9, color=CLR_SCOPE)
ax1.fill_between(df["idx"], df["cum"], alpha=0.10, color=CLR_BURNUP, zorder=2)
ax1.plot(df["idx"], df["cum"], color=CLR_BURNUP, lw=2.5, zorder=3)
if si_x is not None:
    ax1.axvline(si_x, color=CLR_WSTART, lw=1.8, ls="--", zorder=5, alpha=0.85)
    ax1.text(si_x + 0.4, total_ih * 0.72, f"Work Start\n{fmt_wk(start_wk)}", fontsize=8.5, color=CLR_WSTART, va="center", ha="left")
if completion_wk:
    comp_row = df[df["wk"] == completion_wk]
    if not comp_row.empty:
        cidx = int(comp_row.iloc[0]["idx"])
        ax1.axvline(cidx, color=CLR_COMP, lw=2, ls="-", zorder=5, alpha=0.80)
        ax1.text(cidx + 0.4, total_ih * 0.46, f"Done\n{fmt_wk(completion_wk)}", fontsize=8.5, color=CLR_COMP,
                 va="center", ha="left", bbox=dict(boxstyle="round,pad=0.3", fc="#e6f9ee", ec=CLR_COMP, lw=0.8))
for name, wk in milestones.items():
    idx = ms_idx(name)
    if idx is None:
        continue
    color  = MS_COLORS.get(name, "#999")
    is_key = name in ("RG", "SOP", "EG")
    ax1.axvline(idx, color=color, lw=1.8 if is_key else 1.0, ls="-" if is_key else (0,(4,4)), zorder=4, alpha=0.85)
    ax1.text(idx + 0.3, total_ih * 1.025, name, fontsize=8.5, color=color, va="top", ha="left")
STATUS_Y_FRAC = {"RG": 0.55, "SOP": 0.35, "EG": 0.18}
for name in ("RG", "SOP", "EG"):
    s = ms_status.get(name)
    if not s:
        continue
    idx      = ms_idx(name)
    color    = MS_COLORS[name]
    bg       = "#e8f5e9" if s["ok"] else "#ffebee"
    fc       = "#2e7d32" if s["ok"] else "#c62828"
    miss_str = "On track" if s["ok"] else f"Miss {s['miss']:,} IH"
    label    = f"{name}: {s['done']:,}/{total_ih:,} IH\n{miss_str}"
    y_pos    = total_ih * STATUS_Y_FRAC.get(name, 0.4)
    ax1.annotate(label, xy=(idx, get_cum_at(name)), xytext=(idx + 3, y_pos),
                 fontsize=8.5, color=fc, ha="left", va="center",
                 bbox=dict(boxstyle="round,pad=0.4", fc=bg, ec=color, lw=1.2),
                 arrowprops=dict(arrowstyle="-|>", color=color, lw=1.0), annotation_clip=False)
ax1.set_ylim(0, total_ih * 1.12)
ax1.set_ylabel("Cumulative IH", fontsize=10, color="#555", labelpad=8)
ax1.set_title("Cumulative progress  ·  burnup", fontsize=11, color="#444", fontweight="normal", loc="left", pad=8)
b_legend = [
    Line2D([0],[0], color=CLR_BURNUP, lw=2.5, label="Cumulative IH"),
    Line2D([0],[0], color=CLR_SCOPE,  lw=1.5, ls="--", label=f"Scope ({total_ih:,})"),
    Line2D([0],[0], color=CLR_WSTART, lw=1.8, ls="--", label="Work start"),
]
if completion_wk:
    b_legend.append(Line2D([0],[0], color=CLR_COMP, lw=2, label=f"Completion {fmt_wk(completion_wk)}"))
ax1.legend(handles=b_legend, loc="upper left", fontsize=8.5, framealpha=0.9, edgecolor="#ddd", ncol=4)

ax2.set_ylim(0, EXT_YLIM)
ax2.bar(df["idx"], df["sent"], color=CLR_BURNUP, alpha=0.80, zorder=2, width=0.85, label="Team output (sent IH)")
ax2.plot(df["idx"], df["pool"], color=CLR_WORK_GEN, lw=2, ls="--", zorder=3, label="Work available per week")
ax2.plot(df["idx"], df["cap"],  color=CLR_CAPACITY, lw=1.8, ls="-.", zorder=3, alpha=0.85, label="SE capacity")
ax2.axhline(max_y, color="#bbbbbb", lw=0.5, zorder=1)
if si_x is not None:
    ax2.axvline(si_x, color=CLR_WSTART, lw=2, ls="--", zorder=5, alpha=0.85)
    ax2.text(si_x - 0.5, max_y * 0.90, f"Work Start\n{fmt_wk(start_wk)}", fontsize=8.5, color=CLR_WSTART,
             va="top", ha="right", bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=CLR_WSTART, lw=0.7, alpha=0.9))
for i, t in enumerate(tk_objs):
    tc = TRUCK_COLORS[i % len(TRUCK_COLORS)]
    off = i * 0.055
    ax2.axvline(t["ai"], color=tc, lw=1.4, ls="--", zorder=4, alpha=0.85)
    ax2.text(t["ai"] + 0.3, max_y * (0.92 - off), f"T{i+1} Arr", fontsize=8.5, color=tc, va="top", ha="left", fontweight="bold")
    ax2.axvline(t["di"], color=tc, lw=1.4, ls=":",  zorder=4, alpha=0.85)
    ax2.text(t["di"] + 0.3, max_y * (0.83 - off), f"T{i+1} Dep", fontsize=8.5, color=tc, va="top", ha="left", fontweight="bold")
for name, wk in milestones.items():
    idx = ms_idx(name)
    if idx is None:
        continue
    color  = MS_COLORS.get(name, "#999")
    is_key = name in ("RG", "SOP", "EG")
    ax2.axvline(idx, color=color, lw=2.0 if is_key else 1.0, ls="-" if is_key else (0,(4,4)), zorder=4, alpha=0.90)
    ax2.text(idx + 0.2, max_y * 0.97, name, fontsize=9, color=color, rotation=90, va="top", ha="left",
             fontweight="bold" if is_key else "normal")
BOX_Y = {"RG": 0.52, "SOP": 0.34, "EG": 0.18}
for name in ("RG", "SOP", "EG"):
    s = ms_status.get(name)
    if not s:
        continue
    idx   = ms_idx(name)
    color = MS_COLORS[name]
    bg    = "#e8f5e9" if s["ok"] else "#ffebee"
    fc    = "#2e7d32" if s["ok"] else "#c62828"
    label = f"{name} Status\nSent: {s['done']:,}\nMissed: {s['miss']:,}"
    ax2.annotate(label, xy=(idx, max_y * 0.04), xytext=(idx + 2.5, max_y * BOX_Y.get(name, 0.35)),
                 fontsize=9, color=fc, ha="left", va="center", fontweight="bold",
                 bbox=dict(boxstyle="round,pad=0.5", fc=bg, ec=color, lw=1.8),
                 arrowprops=dict(arrowstyle="-|>", color=color, lw=1.4, connectionstyle="arc3,rad=0.1"),
                 annotation_clip=False)

DIM_PAIRS = [("FIG","RG",ARROW_Y[0]), ("RG","SOP",ARROW_Y[1]), ("SOP","EG",ARROW_Y[2])]
for ms1, ms2, arr_y in DIM_PAIRS:
    x1 = ms_idx(ms1)
    x2 = ms_idx(ms2)
    if x1 is None or x2 is None or x1 >= x2:
        continue
    ih_diff = max(0.0, get_cum_at(ms2) - get_cum_at(ms1))
    for xv in (x1, x2):
        ax2.plot([xv, xv], [max_y, arr_y], color="#888888", lw=0.7, ls=":", zorder=1)
    ax2.annotate("", xy=(x2, arr_y), xytext=(x1, arr_y),
                 arrowprops=dict(arrowstyle="<->", color="#333333", lw=1.6, mutation_scale=13),
                 annotation_clip=False)
    ax2.text((x1+x2)/2, arr_y + max_y * 0.025, f"{int(round(ih_diff))} IH",
             ha="center", va="bottom", fontsize=10, fontweight="bold", color="#111111", clip_on=False)

ax2.set_xticks(tick_pos)
ax2.set_xticklabels(tick_lbls, rotation=60, ha="right", fontsize=9)
ax2.set_xlim(df["idx"].min() - 1, df["idx"].max() + 4)
ax2.set_ylabel("Infoheaders / week", fontsize=10, color="#555", labelpad=8)
ax2.set_title("Weekly output detail", fontsize=11, color="#444", fontweight="normal", loc="left", pad=8)
w_legend = [
    mpatches.Patch(facecolor=CLR_BURNUP, alpha=0.80, label="Team output (sent IH)"),
    Line2D([0],[0], color=CLR_WORK_GEN, lw=2,   ls="--", label="Work available"),
    Line2D([0],[0], color=CLR_CAPACITY, lw=1.8, ls="-.", label="SE capacity"),
    mpatches.Patch(facecolor=CLR_BURNUP, alpha=0.12, label="Truck on-site"),
    Line2D([0],[0], color=CLR_WSTART,   lw=1.8, ls="--", label="Work start"),
]
ax2.legend(handles=w_legend, loc="upper right", fontsize=8.5, framealpha=0.9, edgecolor="#ddd")

plt.tight_layout(rect=[0, 0.01, 0.97, 1])
fig.subplots_adjust(hspace=0.06)
st.pyplot(fig)
plt.close(fig)

with st.expander("Milestone detail table"):
    table_rows = []
    for name, wk in milestones.items():
        row = df[df["wk"] == wk]
        if row.empty:
            continue
        done = int(row.iloc[0]["cum"])
        miss = max(0, total_ih - done)
        table_rows.append({
            "Milestone": name, "Week": fmt_wk(wk),
            "IH done": f"{done:,}", "IH miss": f"{miss:,}" if miss > 0 else "—",
            "% done": f"{min(100, round(done / total_ih * 100))}%",
            "Status": "✅ On track" if miss == 0 else "❌ Behind",
        })
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
