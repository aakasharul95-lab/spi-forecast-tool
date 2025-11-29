import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import norm

# --- PAGE CONFIG ---
st.set_page_config(page_title="Workpackage Request Estimation", layout="wide")
st.title("🚛 Workpackage Request Estimation (Multi-Truck)")
st.markdown("Simulate capacity bottlenecks with **Multiple Truck Arrivals**.")

# --- SIDEBAR: GLOBAL SETTINGS ---
st.sidebar.header("1. Global Scope")
total_scope = st.sidebar.number_input("Total Infoheaders", value=1500, step=50)
work_start_week = st.sidebar.number_input("Work Start Week (YYWW)", value=2535)

st.sidebar.header("2. Team Resources")
se_count = st.sidebar.number_input("SE Headcount", value=3)
ih_per_se = st.sidebar.number_input("IH per SE/Week", value=5)
rework_rate = st.sidebar.slider("Rework Rate %", 0.0, 0.5, 0.15)

# --- SIDEBAR: TRUCK CONFIGURATION ---
st.sidebar.divider()
st.sidebar.header("3. Truck Configuration")
num_trucks = st.sidebar.radio("Number of Trucks", [1, 2, 3], horizontal=True)

# Container for truck details
trucks = []
available_truck_scope_pct = 1.0 - (0.10 + 0.10) # Assuming default pre/post work is 10% each

for i in range(num_trucks):
    with st.sidebar.expander(f"🚛 Truck {i+1} Details", expanded=True):
        t_arr = st.number_input(f"T{i+1} Arrival (YYWW)", value=2545 + (i*10))
        t_dep = st.number_input(f"T{i+1} Departure (YYWW)", value=2552 + (i*10))
        # Relative weight: e.g. If T1=50 and T2=50, they split work 50/50.
        t_weight = st.slider(f"T{i+1} Workload Weight", 1, 100, 50, help="Higher number = More infoheaders assigned to this truck.")
        
        trucks.append({
            "id": i+1, "arrival": t_arr, "departure": t_dep, "weight": t_weight
        })

# --- SIDEBAR: WORK SPLIT ---
st.sidebar.divider()
st.sidebar.header("4. Phases")
pre_work_pct = st.sidebar.slider("Pre-Work % (Early Start)", 0.0, 0.5, 0.10)
post_work_pct = st.sidebar.slider("Post-Work % (Cleanup)", 0.0, 0.5, 0.10)

st.sidebar.header("5. Milestones")
fdg_week = st.sidebar.number_input("FDG Week", value=2532)
c_build_week = st.sidebar.number_input("C-Build Week", value=2548)
fig_week = st.sidebar.number_input("FIG Week", value=2605)
rg_week = st.sidebar.number_input("RG Deadline", value=2640)

# --- LOGIC ENGINE ---
max_capacity = se_count * ih_per_se
project_milestones = {"FDG": fdg_week, "C-Build": c_build_week, "FIG": fig_week, "RG": rg_week}

# 1. Timeline Logic (Dynamic Scaling)
# Get min and max dates from all trucks and milestones
all_dates = [work_start_week, fdg_week, c_build_week, 2530]
for t in trucks:
    all_dates.extend([t['arrival'], t['departure']])

earliest_date = min(all_dates)
if earliest_date % 100 <= 2:
    start_week = ((earliest_date // 100) - 1) * 100 + 50
else:
    start_week = earliest_date - 2

latest_date = max(rg_week, max([t['departure'] for t in trucks]))
end_year_diff = (latest_date // 100) - (start_week // 100)
end_week_diff = (latest_date % 100) - (start_week % 100)
total_duration = (end_year_diff * 52) + end_week_diff + 15
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
    
    # Calculate Truck Indices & Sigmas
    for t in trucks:
        t['arr_idx'] = df[df['Week'] == t['arrival']].index[0]
        t['dep_idx'] = df[df['Week'] == t['departure']].index[0]
        t['center'] = (t['arr_idx'] + t['dep_idx']) / 2
        t['sigma'] = (t['dep_idx'] - t['arr_idx']) / 5
except IndexError:
    st.error("⚠️ Date Mismatch: Dates outside calculated timeline. Check Truck/Start dates.")
    st.stop()

# 2. Volume Calculations
demand_pre = total_scope * pre_work_pct
demand_post = total_scope * post_work_pct
demand_trucks_total = total_scope - (demand_pre + demand_post)

# Calculate Weight Ratios
total_weight = sum(t['weight'] for t in trucks)
for t in trucks:
    t['volume'] = demand_trucks_total * (t['weight'] / total_weight)

# Rates
first_arrival_idx = min(t['arr_idx'] for t in trucks)
last_departure_idx = max(t['dep_idx'] for t in trucks)

dur_pre = first_arrival_idx - start_idx
rate_pre = demand_pre / dur_pre if dur_pre > 0 else 0
dur_post = rg_idx - last_departure_idx
rate_post = demand_post / dur_post if dur_post > 0 else 0

# 3. Pre-calculate Bell Curves
for t in trucks:
    curve = []
    for i in range(len(df)):
        val = norm.pdf(i, t['center'], t['sigma']) if t['sigma'] > 0 else 0
        curve.append(val)
    t['raw_curve'] = curve
    t['sum_curve'] = sum(curve)

# 4. Simulation Loop
data = []
backlog = 0
rework_queue = 0
total_rework = 0

for i in range(len(df)):
    new_work = 0
    
    # A. Pre-Work (Until FIRST truck arrives)
    if i >= start_idx and i <= first_arrival_idx:
        new_work += rate_pre
        
    # B. Post-Work (After LAST truck departs)
    if i > last_departure_idx and i <= rg_idx:
        new_work += rate_post
        
    # C. Truck Work (Sum of all trucks)
    for t in trucks:
        if t['sum_curve'] > 0:
            truck_contribution = (t['raw_curve'][i] / t['sum_curve']) * t['volume']
            new_work += truck_contribution

    # Process
    pool = new_work + backlog + rework_queue
    processed = min(pool, max_capacity)
    
    # Rework
    rework_gen = processed * rework_rate
    total_rework += rework_gen
    
    backlog = pool - processed + rework_gen
    rework_queue = 0 
    
    data.append({"Index": i, "Gen": new_work, "Sent": processed, "Backlog": backlog})

res_df = pd.DataFrame(data)
res_df = res_df.merge(df, left_on='Index', right_on='Index')

# --- PLOTTING ---
fig, ax = plt.subplots(figsize=(16, 7))

# Areas
ax.fill_between(res_df['Index'], res_df['Backlog'], color='#ffcccb', alpha=0.6, label='Backlog')
ax.bar(res_df['Index'], res_df['Sent'], color='#005f9e', alpha=0.9, label='Team Output')
ax.plot(res_df['Index'], res_df['Gen'], color='#333333', linestyle='--', linewidth=3, label='Work Generated')

max_y = max(res_df['Backlog'].max(), max_capacity)
if max_y == 0: max_y = 10
ax.set_ylim(0, max_y * 1.35)

bbox = dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.85)

# Markers (Dynamic per truck)
colors_truck = ['green', 'blue', 'teal'] # Different colors for trucks
for t in trucks:
    c = colors_truck[(t['id']-1) % 3]
    # Arrival
    ax.axvline(t['arr_idx'], color=c, linestyle=':')
    ax.text(t['arr_idx'], max_y*(1.0 + 0.05*t['id']), f"T{t['id']} Arr", color=c, ha='center', fontweight='bold', bbox=bbox)
    # Departure
    ax.axvline(t['dep_idx'], color='orange', linestyle=':')
    # Only label departures if they aren't crowded, or just define it in legend

# Standard Markers
ax.axvline(start_idx, color='blue', linestyle='-.')
ax.text(start_idx, max_y*1.1, "Work Start", color='blue', ha='center', bbox=bbox)

# Gates
gate_colors = {"FDG": "purple", "C-Build": "#d4af37", "FIG": "brown", "RG": "black"}
for name, wk in project_milestones.items():
    if wk in res_df['Week'].values:
        idx = res_df[res_df['Week'] == wk].index[0]
        c = gate_colors.get(name, 'black')
        ax.axvline(idx, color=c, linestyle='-.')
        ax.text(idx, max_y*0.85, f" {name} ", color=c, rotation=90, bbox=bbox)

# Missed Logic
missed = res_df[res_df['Week'] == rg_week]['Backlog'].values[0]
if missed > 1:
    ax.annotate(f'MISSED: {int(missed)}', xy=(rg_idx, missed), xytext=(rg_idx-5, missed+(max_y*0.1)),
                arrowprops=dict(facecolor='red', shrink=0.05), fontsize=14, color='white', bbox=dict(boxstyle="round", fc="red"))
else:
    ax.text(rg_idx, max_y*0.5, "✅ ON TARGET", color='green', ha='center', fontsize=16, fontweight='bold', bbox=bbox)

ax.set_ylabel("Infoheaders")
ax.grid(True, alpha=0.3)
ax.legend(loc='upper left')
step = 2 if len(res_df) < 80 else 4
ax.set_xticks(res_df['Index'][::step])
ax.set_xticklabels(res_df['Week_Str'][::step], rotation=90)

st.pyplot(fig)

# --- METRICS ---
c1, c2, c3, c4 = st.columns(4)
c1.metric("Original Scope", f"{int(total_scope)}")
c2.metric("Rework Added", f"{int(total_rework)}")
c3.metric("Effective Load", f"{int(total_scope + total_rework)}")
if missed > 0:
    c4.metric("Missed at RG", f"{int(missed)}", delta="Risk", delta_color="inverse")
else:
    c4.metric("Status", "Success", delta="On Track")

import time

# --- 1. SETUP SESSION STATE ---
if 'egg_counter' not in st.session_state:
    st.session_state.egg_counter = 0

# --- 2. DEFINE THE CLICK ACTION (The Callback) ---
def click_egg():
    st.session_state.egg_counter += 1

# --- 3. THE BUTTON ---
# Note: We use 'on_click=click_egg' to ensure it counts reliably
st.sidebar.button("Version 1.01", on_click=click_egg)

# --- 4. DEBUGGING (Optional: See if it works) ---
# Uncomment the line below to see the number update on screen for testing
# st.sidebar.write(f"Count: {st.session_state.egg_counter}")

# --- 5. THE TRIGGER LOGIC ---
if st.session_state.egg_counter >= 5:
    
    # Reset the counter immediately so it doesn't loop forever
    st.session_state.egg_counter = 0
    
    # Run the Animation
    with st.spinner("🔄 RE-CALCULATING INTELLIGENCE ALGORITHMS..."):
        time.sleep(1.5)
    
    st.balloons()
    
    # Show the Message
    with st.expander("🚨 SYSTEM DEFINITION UPDATE", expanded=True):
        st.markdown("""
            ### 🤖 ACRONYM UPDATE
            The system has officially redefined **'AI'**.
            <br>It no longer stands for *Artificial Intelligence*.
            <br>It now stands for **Aakash Intelligence**.
        """, unsafe_allow_html=True)
        
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
            
        st.info("System Conclusion: Aakash is better than Tobias.")







