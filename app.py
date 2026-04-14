import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
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
ih_per_se = st.sidebar.number_input("IH per SE/Week", value=5.0, step=0.1)

st.sidebar.divider()
st.sidebar.header("3. Choose the number of trucks you will receive")

num_trucks_input = st.sidebar.number_input("Number of Trucks", min_value=0.10, max_value=10.00, value=3.00, step=0.10, format="%.2f")
ui_truck_count = math.ceil(num_trucks_input)

trucks = []
for i in range(ui_truck_count):
    with st.sidebar.expander(f"🚛 Truck {i+1} Details", expanded=True):
        default_arr = 2545 + (i*10)
        if default_arr % 100 > 52: default_arr = (default_arr // 100 + 1) * 100 + 1
        
        t_arr = st.number_input(f"T{i+1} Arrival (YYWW)", value=default_arr)
        t_dep = st.number_input(f"T{i+1} Departure (YYWW)", value=t_arr + 8)
        
        fraction = round(num_trucks_input % 1, 2)
        is_fractional = (i == ui_truck_count - 1 and fraction > 0)
        physical_size = fraction if is_fractional else 1.0

        t_weight = st.slider(f"T{i+1} Workload (%)", 1, 100, 100, key=f"t_weight_{i}")
        trucks.append({
            "id": i+1, 
            "arrival": t_arr, 
            "departure": t_dep, 
            "weight": t_weight,
            "physical_size": physical_size
        })

st.sidebar.divider()
st.sidebar.header("4. Phases")
pre_work_pct = st.sidebar.slider("Pre-Work % ", 0.0, 0.5, 0.10)
post_work_pct = st.sidebar.slider("Post-Work % ", 0.0, 0.5, 0.10, help="This work is distributed in the empty weeks BETWEEN trucks and AFTER the last truck.")

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

max_project_weight = ui_truck_count * 100.0

total_effective_weight = 0
for t in trucks:
    t['effective_weight'] = t['physical_size'] * t['weight']
    total_effective_weight += t['effective_weight']

unassigned_volume = 0
if total_effective_weight < max_project_weight:
    unassigned_volume = demand_trucks_total * ((max_project_weight - total_effective_weight) / max_project_weight)

for t in trucks:
    t['volume'] = demand_trucks_total * (t['effective_weight'] / max_project_weight)

first_arrival_idx = min(t['arr_idx'] for t in trucks)

# --- Rates ---
dur_pre = first_arrival_idx - start_idx
# NEW: Catch impossible pre-work
if dur_pre > 0:
    rate_pre = demand_pre / dur_pre
else:
    rate_pre = 0
    unassigned_volume += demand_pre

truck_windows = [(t['arr_idx'], t['dep_idx']) for t in trucks]
gap_indices = [
    i for i in range(first_arrival_idx + 1, rg_idx + 1)
    if not any(start <= i <= end for start, end in truck_windows)
]

# NEW: Catch impossible post-work
if len(gap_indices) > 0:
    rate_post = demand_post / len(gap_indices)
else:
    rate_post = 0
    unassigned_volume += demand_post

# --- Bell Curves ---
for t in trucks:
    curve = []
    # NEW: Hard Cutoff exactly at Departure or RG (whichever is earlier)
    cutoff_idx = min(rg_idx, t['dep_idx'])
    
    for i in range(len(df)):
        if i <= cutoff_idx and t['sigma'] > 0:
            val = norm.pdf(i, t['center'], t['sigma'])
        else:
            val = 0
        curve.append(val)
        
    t['raw_curve'] = curve
    t['sum_curve'] = sum(curve)

# --- Simulation Loop ---
data = []
backlog = 0

for i in range(len(df)):
    new_work = 0
    if i >= start_idx and i <= first_arrival_idx:
        new_work += rate_pre
    if i in gap_indices:
        new_work += rate_post
    for t in trucks:
        if t['sum_curve'] > 0:
            new_work += (t['raw_curve'][i] / t['sum_curve']) * t['volume']

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

ax.set_ylim(0, max_y * (1.2 + 0.05 * ui_truck_count))

bbox = dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.85)

colors_truck = ['green', 'blue', 'teal', 'magenta', 'darkorange', 'purple', 'cyan', 'brown', 'crimson', 'olive']
for t in trucks:
    c = colors_truck[(t['id']-1) % len(colors_truck)]
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

# --- COMBINED RISK ANNOTATION ---
backlog_at_rg = res_df[res_df['Week'] == rg_week]['Backlog'].values[0]
total_missed = backlog_at_rg + unassigned_volume

if total_missed > 1:
    ax.annotate(f'MISSED: {int(total_missed)} IH', xy=(rg_idx, 0), xytext=(rg_idx-5, max_y*0.5),
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

# --- SIMPLIFIED METRICS PANEL ---
c1, c2, c3 = st.columns(3)
c1.metric("Total Scope", f"{int(total_scope)}")

if total_missed > 0:
    c2.metric("Missed at RG", f"{int(total_missed)}", delta="Risk", delta_color="inverse")
else:
    c2.metric("Status", "Success", delta="On Track")

# =========================================================
# 4. EASTER EGG (v1.01)
# =========================================================
st.sidebar.divider()
if 'egg_counter' not in st.session_state: st.session_state.egg_counter = 0
def click_egg(): st.session_state.egg_counter += 1
st.sidebar.button("Version 1.01", on_click=click_egg)

if st.session_state.egg_counter >= 5:
    st.session_state.egg_counter = 0
    with st.spinner("🔄 RE-CALCULATING INTELLIGENCE ALGORITHMS..."): time.sleep(1.5)
    st.balloons()
    with st.expander("🚨 SYSTEM DEFINITION UPDATE", expanded=True):
        st.markdown("""### 🤖 ACRONYM UPDATE
The system has officially redefined **'AI'**.
<br>It no longer stands for *Artificial Intelligence*.
<br>It now stands for **Aakash Intelligence**.""", unsafe_allow_html=True)
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
