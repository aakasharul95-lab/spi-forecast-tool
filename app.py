import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import norm
import time
import math

# --- PAGE CONFIG ---
st.set_page_config(page_title="Workpackage Request Estimation", layout="wide")
st.title("🚛 Workpackage Request Estimation")

# =========================================================
# 1. SIDEBAR CONFIGURATION
# =========================================================
st.sidebar.header("1. Global Scope")
total_scope = st.sidebar.number_input("Total Infoheaders", value=1500, step=50)
work_start_week = st.sidebar.number_input("Work Start Week (YYWW)", value=2535)

st.sidebar.header("2. Team Resources")
se_count = st.sidebar.number_input("SE Headcount", value=3.0, step=0.5)

with st.sidebar.expander("📈 Dynamic Capacity Curve", expanded=True):
    peak_ih = st.slider("Peak Weekly Capacity", 1.0, 25.0, 8.0)
    cap_center_offset = st.slider("Curve Peak Position", -10, 50, 15, help="Weeks relative to Work Start")
    cap_width = st.slider("Ramp-up/down Smoothness", 5, 150, 45)

st.sidebar.divider()
st.sidebar.header("⚙️ Simulation Mode")
pure_capacity_mode = st.sidebar.toggle(
    "Pure Capacity Mode", 
    value=True, 
    help="When active, work is aggressively front-loaded starting at the Start Week."
)

st.sidebar.divider()
st.sidebar.header("3. Choose the number of trucks")
num_trucks_input = st.sidebar.number_input("Number of Trucks", min_value=0.10, max_value=10.00, value=3.00, step=0.10, format="%.2f")
ui_truck_count = math.ceil(num_trucks_input)

trucks = []
for i in range(ui_truck_count):
    with st.sidebar.expander(f"🚛 Truck {i+1} Details", expanded=True):
        default_arr = 2545 + (i*10)
        if default_arr % 100 > 52: default_arr = (default_arr // 100 + 1) * 100 + 1
        
        t_arr = st.number_input(f"T{i+1} Arrival (YYWW)", value=default_arr, key=f"arr_{i}")
        t_dep = st.number_input(f"T{i+1} Departure (YYWW)", value=t_arr + 8, key=f"dep_{i}")
        
        fraction = round(num_trucks_input % 1, 2)
        is_fractional = (i == ui_truck_count - 1 and fraction > 0)
        physical_size = fraction if is_fractional else 1.0
        t_weight = st.slider(f"T{i+1} Workload (%)", 1, 100, 100, key=f"t_weight_{i}")
        
        trucks.append({
            "id": i+1, "arrival": t_arr, "departure": t_dep, 
            "weight": t_weight, "physical_size": physical_size
        })

st.sidebar.divider()
st.sidebar.header("4. Phases")
pre_work_pct = st.sidebar.slider("Pre-Work % ", 0.0, 0.5, 0.10)
post_work_pct = st.sidebar.slider("Post-Work % ", 0.0, 0.5, 0.10)

st.sidebar.header("5. Milestones")
fdg_week = st.sidebar.number_input("FDG Week", value=2532)
c_build_week = st.sidebar.number_input("C-Build Week", value=2548)
fig_week = st.sidebar.number_input("FIG Week", value=2605)
rg_week = st.sidebar.number_input("RG Deadline", value=2620)
sop_week = st.sidebar.number_input("SOP Milestone", value=2630)
eg_week = st.sidebar.number_input("EG Milestone", value=2640)

# =========================================================
# 2. LOGIC ENGINE
# =========================================================
project_milestones = {"FDG": fdg_week, "C-Build": c_build_week, "FIG": fig_week, "RG": rg_week, "SOP": sop_week, "EG": eg_week}

def generate_yyww_timeline(start, duration):
    timeline = []
    current = start
    for _ in range(duration):
        timeline.append(current)
        year, week = current // 100, current % 100
        if week >= 52: year += 1; week = 1
        else: week += 1
        current = year * 100 + week
    return timeline

# Timeline Generation
weeks = generate_yyww_timeline(min(work_start_week, fdg_week) - 2, 120)
df = pd.DataFrame({'Week': weeks})
df['Week_Str'] = df['Week'].astype(str)
df['Index'] = range(len(df))

try:
    start_idx = df[df['Week'] == work_start_week].index[0]
    rg_idx = df[df['Week'] == rg_week].index[0]
    for t in trucks:
        t['arr_idx'] = df[df['Week'] == t['arrival']].index[0] if t['arrival'] in df['Week'].values else 0
        t['dep_idx'] = df[df['Week'] == t['departure']].index[0] if t['departure'] in df['Week'].values else len(df)-1
        t['center'] = (t['arr_idx'] + t['dep_idx']) / 2
        span = t['dep_idx'] - t['arr_idx']
        t['sigma'] = span / 5 if span > 0 else 0.5
except:
    st.error("Check YYWW dates."); st.stop()

# --- DYNAMIC CAPACITY CURVE ---
indices = np.arange(len(df))
peak_index = start_idx + cap_center_offset
capacity_curve = peak_ih * np.exp(-((indices - peak_index)**2) / (2 * cap_width**2))

# --- WORK GENERATION LOGIC ---
demand_pre = total_scope * pre_work_pct
demand_post = total_scope * post_work_pct
demand_trucks_total = total_scope - (demand_pre + demand_post)
total_eff_weight = sum(t['physical_size'] * t['weight'] for t in trucks)
safe_den = max(0.01, total_eff_weight)

for t in trucks:
    t['volume'] = demand_trucks_total * ((t['physical_size'] * t['weight']) / safe_den)
    t['raw_curve'] = [norm.pdf(i, t['center'], t['sigma']) for i in range(len(df))]
    t['sum_curve'] = sum(t['raw_curve'])

first_arrival_idx = min(t['arr_idx'] for t in trucks)
dur_pre = max(1, first_arrival_idx - start_idx)
rate_pre = demand_pre / dur_pre

truck_windows = [(t['arr_idx'], t['dep_idx']) for t in trucks]
gap_indices = [i for i in range(first_arrival_idx + 1, rg_idx + 1) if not any(s <= i <= e for s, e in truck_windows)]
rate_post = demand_post / len(gap_indices) if gap_indices else 0

# --- SIMULATION LOOP ---
data, backlog = [], 0
for i in range(len(df)):
    new_work = 0
    if pure_capacity_mode:
        agg_sigma, agg_center = 2.0, start_idx + 2
        val = norm.pdf(i, agg_center, agg_sigma) if i >= start_idx else 0
        norm_factor = sum([norm.pdf(j, agg_center, agg_sigma) if j >= start_idx else 0 for j in range(len(df))])
        new_work = (val / norm_factor) * total_scope if norm_factor > 0 else 0
    else:
        if i >= start_idx and i < first_arrival_idx: new_work += rate_pre
        if i in gap_indices: new_work += rate_post
        for t in trucks:
            if t['sum_curve'] > 0: new_work += (t['raw_curve'][i] / t['sum_curve']) * t['volume']

    pool = new_work + backlog
    cur_cap = capacity_curve[i]
    processed = min(pool, cur_cap)
    backlog = pool - processed
    data.append({"Index": i, "Gen": new_work, "Sent": processed, "Backlog": backlog, "Cap": cur_cap})

res_df = pd.DataFrame(data).merge(df, on='Index')
res_df['Cumulative_Sent'] = res_df['Sent'].cumsum()

# =========================================================
# 3. VISUALIZATION
# =========================================================
fig, ax = plt.subplots(figsize=(16, 8))
ax.bar(res_df['Index'], res_df['Sent'], color='#005f9e', alpha=0.9, label='Team Output (Sent IH)')
ax.plot(res_df['Index'], res_df['Gen'], color='#333333', linestyle='--', linewidth=3, label='Work Generated')
ax.plot(res_df['Index'], res_df['Cap'], color='red', linestyle='--', alpha=0.6, label='Capacity Curve')
ax.fill_between(res_df['Index'], res_df['Cap'], color='red', alpha=0.05)

max_y = max(res_df['Gen'].max(), res_df['Cap'].max()) * 1.5
ax.set_ylim(0, max_y)
bbox = dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.85)

# Status Boxes and Dimension Lines
target_milestones = [("RG", rg_week, 0.65), ("SOP", sop_week, 0.45), ("EG", eg_week, 0.25)]
prev_idx, prev_comp = start_idx, 0
span_y = max_y * 1.2

for m_name, m_wk, y_pct in target_milestones:
    if m_wk in res_df['Week'].values:
        row = res_df[res_df['Week'] == m_wk].iloc[0]
        idx, comp = row['Index'], row['Cumulative_Sent']
        missed = total_scope - comp
        bg = "#28a745" if missed < 1 else "#dc3545"
        
        ax.annotate(f"{m_name} Status\nSent: {int(comp)} ({comp/total_scope:.1%})\nMiss: {int(missed)}", 
                    xy=(idx, 0), xytext=(idx-5, max_y*y_pct), color='white', fontweight='bold',
                    arrowprops=dict(facecolor=bg, shrink=0.05, width=2), bbox=dict(boxstyle="round", fc=bg))
        
        if prev_idx < idx:
            ax.annotate('', xy=(prev_idx, span_y), xytext=(idx, span_y), arrowprops=dict(arrowstyle='<->'))
            ax.text((prev_idx+idx)/2, span_y, f"{int(comp-prev_comp)} IH", ha='center', va='bottom', fontweight='bold')
        prev_idx, prev_comp = idx, comp

for name, wk in project_milestones.items():
    if wk in res_df['Week'].values:
        idx = res_df[res_df['Week'] == wk].index[0]
        ax.axvline(idx, color='gray', linestyle='-.', alpha=0.4)
        ax.text(idx, max_y*0.9, name, rotation=90, bbox=bbox)

ax.legend(loc='upper left'); ax.set_xticks(res_df['Index'][::4]); ax.set_xticklabels(res_df['Week_Str'][::4], rotation=90)
st.pyplot(fig)

# Metrics and Easter Egg
st.sidebar.button("Version 1.01", on_click=lambda: st.session_state.update({"egg": st.session_state.get("egg", 0)+1}))
if st.session_state.get("egg", 0) >= 5:
    st.balloons(); st.info("System Conclusion: Aakash is better than Tobias in every imaginable way")
