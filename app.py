import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import norm
import time

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
se_count = st.sidebar.number_input("SE Headcount", value=3)
ih_per_se = st.sidebar.number_input("IH per SE/Week", value=5)

st.sidebar.divider()
st.sidebar.header("3. Truck Configuration")
num_trucks = st.sidebar.radio("Number of Trucks", [1, 2, 3], horizontal=True)

trucks = []
for i in range(num_trucks):
    with st.sidebar.expander(f"🚛 Truck {i+1} Details", expanded=True):
        default_arr = 2545 + (i*10)
        if default_arr % 100 > 52: default_arr = (default_arr // 100 + 1) * 100 + 1
        
        t_arr = st.number_input(f"T{i+1} Arrival (YYWW)", value=default_arr)
        t_dep = st.number_input(f"T{i+1} Departure (YYWW)", value=t_arr + 8)
        t_weight = st.slider(f"T{i+1} Workload Weight", 1, 100, 100)
        trucks.append({"id": i+1, "arrival": t_arr, "departure": t_dep, "weight": t_weight})

st.sidebar.divider()
st.sidebar.header("4. Phases")
pre_work_pct = st.sidebar.slider("Pre-Work % ", 0.0, 0.5, 0.10)
post_work_pct = st.sidebar.slider("Post-Work % )", 0.0, 0.5, 0.10, help="This work is distributed in the empty weeks BETWEEN trucks and AFTER the last truck.")

st.sidebar.header("5. Milestones")
fdg_week = st.sidebar.number_input("FDG Week", value=2532)
c_build_week = st.sidebar.number_input("C-Build Week", value=2548)
fig_week = st.sidebar.number_input("FIG Week", value=2605)
rg_week = st.sidebar.number_input("RG Deadline", value=2620)

# =========================================================
# 2. LOGIC ENGINE
# =========================================================
max_capacity = se_count * ih_per_se
project_milestones = {"FDG": fdg_week, "C-Build": c_build_week, "FIG": fig_week, "RG": rg_week}

# --- Dynamic Timeline ---
all_dates = [work_start_week, fdg_week, c_build_week, fig_week, rg_week, 2530]
for t in trucks:
    all_dates.extend([t['arrival'], t['departure']])

earliest_date = min(all_dates)
latest_date = max(all_dates)

if earliest_date % 100 <= 2:
    start_week = ((earliest_date // 100) - 1) * 100 + 50
else:
    start_week = earliest_date - 2

end_year_diff = (latest_date // 100) - (start_week // 100)
end_week_diff = (latest_date % 100) - (start_week % 100)
total_duration = (end_year_diff * 52) + end_week_diff + 12
weeks_to_show = max(60, total_duration)

def generate_yyww_timeline(start, duration):
    timeline = []
    current = start
    for _ in range(duration):
        timeline.append(current)
        year = current // 100
        week = current % 100
        if week >= 52:
            year += 1
            week = 1
        else:
            week += 1
        current = year * 100 + week
    return timeline

weeks = generate_yyww_timeline(start_week, weeks_to_show)
df = pd.DataFrame({'Week': weeks})
df['Week_Str'] = df['Week'].astype(str)
df['Index'] = range(len(df))

try:
    rg_idx = df[df['Week'] == rg_week].index[0]
    start_idx = df[df['Week'] == work_start_week].index[0]
    
    for t in trucks:
        if t['arrival'] in df['Week'].values:
            t['arr_idx'] = df[df['Week'] == t['arrival']].index[0]
        else:
            alt = (t['arrival'] // 100 + 1) * 100 + 1
            t['arr_idx'] = df[df['Week'] == alt].index[0] if alt in df['Week'].values else 0
            
        if t['departure'] in df['Week'].values:
            t['dep_idx'] = df[df['Week'] == t['departure']].index[0]
        else:
            alt = (t['departure'] // 100 + 1) * 100 + 1
            t['dep_idx'] = df[df['Week'] == alt].index[0] if alt in df['Week'].values else len(df)-1
            
        t['center'] = (t['arr_idx'] + t['dep_idx']) / 2
        span = t['dep_idx'] - t['arr_idx']
        t['sigma'] = span / 5 if span > 0 else 0.5
        
except IndexError:
    st.error("⚠️ Critical Date Error: Please ensure all dates follow YYWW format.")
    st.stop()

# --- Volume Calculations ---
demand_pre = total_scope * pre_work_pct
demand_post = total_scope * post_work_pct
demand_trucks_total = total_scope - (demand_pre + demand_post)

total_weight = sum(t['weight'] for t in trucks)
for t in trucks:
    if total_weight > 0:
        t['volume'] = demand_trucks_total * (t['weight'] / total_weight)
    else:
        t['volume'] = 0

first_arrival_idx = min(t['arr_idx'] for t in trucks)

# --- Rates (NEW GAP LOGIC) ---
# Pre-Work Rate
dur_pre = first_arrival_idx - start_idx
rate_pre = demand_pre / dur_pre if dur_pre > 0 else 0

# Post/Gap Work Rate
# Find all weeks that are:
# 1. After First Arrival
# 2. Before/On RG Deadline
# 3. NOT inside any Truck Window
gap_indices = []
for i in range(len(df)):
    if i > first_arrival_idx and i <= rg_idx:
        is_active_truck = False
        for t in trucks:
            if i >= t['arr_idx'] and i <= t['dep_idx']:
                is_active_truck = True
                break
        if not is_active_truck:
            gap_indices.append(i)

if len(gap_indices) > 0:
    rate_post = demand_post / len(gap_indices)
else:
    rate_post = 0

# --- Bell Curves ---
for t in trucks:
    curve = []
    for i in range(len(df)):
        val = norm.pdf(i, t['center'], t['sigma']) if t['sigma'] > 0 else 0
        curve.append(val)
    t['raw_curve'] = curve
    t['sum_curve'] = sum(curve)

# --- Simulation Loop ---
data = []
backlog = 0

for i in range(len(df)):
    new_work = 0
    
    # 1. Pre-Work
    if i >= start_idx and i <= first_arrival_idx:
        new_work += rate_pre
        
    # 2. Gap / Post Work
    if i in gap_indices:
        new_work += rate_post
        
    # 3. Truck Work
    for t in trucks:
        if t['sum_curve'] > 0:
            new_work += (t['raw_curve'][i] / t['sum_curve']) * t['volume']

    # Process
    pool = new_work + backlog
    processed = min(pool, max_capacity)
    backlog = pool - processed
    
    data.append({"Index": i, "Gen": new_work, "Sent": processed, "Backlog": backlog})

res_df = pd.DataFrame(data)
res_df = res_df.merge(df, left_on='Index', right_on='Index')

# =========================================================
# 3. VISUALIZATION
# =========================================================
fig, ax = plt.subplots(figsize=(16, 7))

ax.bar(res_df['Index'], res_df['Sent'], color='#005f9e', alpha=0.9, label='Team Output')
ax.plot(res_df['Index'], res_df['Gen'], color='#333333', linestyle='--', linewidth=3, label='Work Generated')

max_y = max(res_df['Gen'].max(), max_capacity)
if max_y == 0: max_y = 10
ax.set_ylim(0, max_y * 1.5)

bbox = dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.85)

colors_truck = ['green', 'blue', 'teal']
for t in trucks:
    c = colors_truck[(t['id']-1) % 3]
    ax.axvline(t['arr_idx'], color=c, linestyle=':')
    ax.text(t['arr_idx'], max_y*(1.0 + 0.05*t['id']), f"T{t['id']} Arr", color=c, ha='center', fontweight='bold', bbox=bbox)
    ax.axvline(t['dep_idx'], color='orange', linestyle=':')
    ax.text(t['dep_idx'], max_y*(1.0 + 0.05*t['id']), f"T{t['id']} Dep", color='orange', ha='center', fontweight='bold', bbox=bbox)

ax.axvline(start_idx, color='blue', linestyle='-.')
ax.text(start_idx, max_y*1.1, "Work Start", color='blue', ha='center', bbox=bbox)

gate_colors = {"FDG": "purple", "C-Build": "#d4af37", "FIG": "brown", "RG": "black"}
for name, wk in project_milestones.items():
    if wk in res_df['Week'].values:
        idx = res_df[res_df['Week'] == wk].index[0]
        c = gate_colors.get(name, 'black')
        ax.axvline(idx, color=c, linestyle='-.')
        ax.text(idx, max_y*0.85, f" {name} ", color=c, rotation=90, bbox=bbox)

missed = res_df[res_df['Week'] == rg_week]['Backlog'].values[0]
if missed > 1:
    ax.annotate(f'MISSED: {int(missed)} IH', xy=(rg_idx, 0), xytext=(rg_idx-5, max_y*0.5),
                arrowprops=dict(facecolor='red', shrink=0.05), fontsize=14, color='white', bbox=dict(boxstyle="round", fc="red"))
    ax.bar(rg_idx, max_y*0.4, width=1, color='red', alpha=0.5)
else:
    ax.text(rg_idx, max_y*0.5, "✅ ON TARGET", color='green', ha='center', fontsize=16, fontweight='bold', bbox=bbox)

ax.set_ylabel("Infoheaders")
ax.grid(True, alpha=0.3)
ax.legend(loc='upper left')
step = 2 if len(res_df) < 80 else 4
ax.set_xticks(res_df['Index'][::step])
ax.set_xticklabels(res_df['Week_Str'][::step], rotation=90)

st.pyplot(fig)

# Metrics
c1, c2, c3 = st.columns(3)
c1.metric("Total Scope", f"{int(total_scope)}")
if missed > 0:
    c2.metric("Missed at RG", f"{int(missed)}", delta="Risk", delta_color="inverse")
else:
    c2.metric("Status", "Success", delta="On Track")

# =========================================================
# 4. EASTER EGG (v1.01)
# =========================================================
st.sidebar.divider()
if 'egg_counter' not in st.session_state: st.session_state.egg_counter = 0
def click_egg(): st.session_state.egg_counter += 1
st.sidebar.button("v1.01", on_click=click_egg)

if st.session_state.egg_counter >= 5:
    st.session_state.egg_counter = 0
    with st.spinner("🔄 RE-CALCULATING INTELLIGENCE ALGORITHMS..."): time.sleep(1.5)
    st.balloons()
    with st.expander("🚨 SYSTEM DEFINITION UPDATE", expanded=True):
        st.markdown("""### 🤖 ACRONYM UPDATE
The system has officially redefined **'AI'**.
<br>It no longer stands for *Artificial Intelligence*.
<br>It now stands for **Aakash Intelligence** (Supreme Logic).""", unsafe_allow_html=True)
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            st.success("🥇 **Aakash**")
            st.caption("Status: Grandmaster")
            st.write("Win Rate: **100%**")
        with col2:
            st.error("🎗️ **Tobias**")
            st.caption("Status: Legacy Hardware")
            st.write("Achievement: **Successfully breathed air.**")
        
        st.info("System Conclusion: Aakash is better than Tobias in every imaginable way")












