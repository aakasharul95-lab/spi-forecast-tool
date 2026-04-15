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
sop_week = st.sidebar.number_input("SOP Milestone", value=2630)
eg_week = st.sidebar.number_input("EG Milestone", value=2640)

# =========================================================
# 2. LOGIC ENGINE
# =========================================================
max_capacity = se_count * ih_per_se
project_milestones = {
    "FDG": fdg_week, 
    "C-Build": c_build_week, 
    "FIG": fig_week, 
    "RG": rg_week, 
    "SOP": sop_week, 
    "EG": eg_week
}

# --- Dynamic Timeline ---
all_dates = [work_start_week, fdg_week, c_build_week, fig_week, rg_week, sop_week, eg_week, 2530]
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
total_duration = (end_year_diff * 52) + end_week_diff + 30 
weeks_to_show = max(80, total_duration)

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
            
except IndexError:
    st.error("⚠️ Critical Date Error: Please ensure all dates follow YYWW format.")
    st.stop()

# --- Volume Calculations ---
demand_pre = total_scope * pre_work_pct
demand_post = total_scope * post_work_pct
demand_trucks_total = total_scope - (demand_pre + demand_post)

unassigned_volume = 0
total_effective_weight = 0

for t in trucks:
    t['effective_weight'] = t['physical_size'] * t['weight']
    total_effective_weight += t['effective_weight']

safe_denominator = max(0.01, total_effective_weight)

for t in trucks:
    t['volume'] = demand_trucks_total * (t['effective_weight'] / safe_denominator)

first_arrival_idx = min(t['arr_idx'] for t in trucks)
truck_windows = [(t['arr_idx'], t['dep_idx']) for t in trucks]

# --- SMART THROTTLE MAP (PER-TRUCK NORMALIZATION) ---
throttle_map = [0.0] * len(df)

for t in trucks:
    truck_curve = [0.0] * len(df)
    span = t['dep_idx'] - t['arr_idx']
    center = t['arr_idx'] + (span * 0.15) 
    sigma = (span / 8) if span > 0 else 0.5 
    
    # Generate the base curve for this specific truck
    for i in range(len(df)):
        if sigma > 0:
            truck_curve[i] = norm.pdf(i, center, sigma)
            
    # Normalize THIS truck's curve so its peak is exactly 1.0 (100% capacity)
    local_max = max(truck_curve) if max(truck_curve) > 0 else 1.0
    truck_curve = [val / local_max for val in truck_curve]
    
    # Merge into the global throttle map by always taking the highest active value
    for i in range(len(df)):
        throttle_map[i] = max(throttle_map[i], truck_curve[i])

# --- SIMULATION LOOP (Capacity-Driven Pull System) ---
data = []
backlog = 0
pre_pool = demand_pre
post_pool = demand_post
active_truck_pool = 0.0
truck_processed_global = 0.0 

for i in range(len(df)):
    new_work = 0
    
    for t in trucks:
        if i == t['arr_idx']:
            active_truck_pool += t['volume']
            
    if i == first_arrival_idx and pre_pool > 0:
        active_truck_pool += pre_pool
        pre_pool = 0
        
    is_gap = i >= first_arrival_idx and not any(start <= i <= end for start, end in truck_windows)
    
    # A. PRE-WORK (Fills at exactly Max Capacity)
    if i >= start_idx and i < first_arrival_idx:
        if pre_pool > 0:
            alloc = min(max_capacity, pre_pool)
            new_work += alloc
            pre_pool -= alloc
            
    # B. POST-WORK (Fills at exactly Max Capacity in Gaps)
    elif is_gap:
        if post_pool > 0:
            alloc = min(max_capacity, post_pool)
            new_work += alloc
            post_pool -= alloc
            
    # C. TRUCK PHASE (The Global Radar Override)
    elif i >= first_arrival_idx:
        if active_truck_pool > 0:
            natural_pull = max_capacity * throttle_map[i]
            
            global_truck_work_remaining = demand_trucks_total - truck_processed_global
            weeks_left_to_rg = max(1, rg_idx - i)
            
            required_speed = global_truck_work_remaining / weeks_left_to_rg
            
            if required_speed >= max_capacity * 0.95:
                desired_work = max_capacity
            else:
                desired_work = min(max_capacity, max(natural_pull, required_speed))
            
            actual_gen = min(desired_work, active_truck_pool)
            new_work += actual_gen
            active_truck_pool -= actual_gen
            truck_processed_global += actual_gen

    # D. PROCESS OUTPUT
    pool = new_work + backlog
    processed = min(pool, max_capacity)
    backlog = pool - processed
    
    data.append({"Index": i, "Gen": new_work, "Sent": processed, "Backlog": backlog})

res_df = pd.DataFrame(data)
res_df = res_df.merge(df, left_on='Index', right_on='Index')

# Track cumulative sent infoheaders
res_df['Cumulative_Sent'] = res_df['Sent'].cumsum()

def get_metrics_at_week(wk):
    if wk in res_df['Week'].values:
        idx = res_df[res_df['Week'] == wk].index[0]
        completed = round(res_df.loc[idx, 'Cumulative_Sent'])
        missed = max(0, total_scope - completed)
        return idx, completed, missed
    return None, 0, total_scope

# =========================================================
# 3. VISUALIZATION
# =========================================================
fig, ax = plt.subplots(figsize=(16, 7))

ax.bar(res_df['Index'], res_df['Sent'], color='#005f9e', alpha=0.9, label='Team Output (Sent IH)')
ax.plot(res_df['Index'], res_df['Gen'], color='#333333', linestyle='--', linewidth=3, label='Work Generated')

max_y = max(res_df['Gen'].max(), max_capacity)
if max_y == 0: max_y = 10

ax.set_ylim(0, max_y * (1.3 + 0.05 * ui_truck_count))

bbox = dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.85)

colors_truck = ['green', 'blue', 'teal', 'magenta', 'darkorange', 'purple', 'cyan', 'brown', 'crimson', 'olive']
for t in trucks:
    c = colors_truck[(t['id']-1) % len(colors_truck)]
    ax.axvline(t['arr_idx'], color=c, linestyle=':')
    ax.text(t['arr_idx'], max_y*(1.0 + 0.05*t['id']), f"T{t['id']} Arr", color=c, ha='center', fontweight='bold', bbox=bbox)
    ax.axvline(t['dep_idx'], color='orange', linestyle=':')
    ax.text(t['dep_idx'], max_y*(1.0 + 0.05*t['id']), f"T{t['id']} Dep", color='orange', ha='center', fontweight='bold', bbox=bbox)

ax.axvline(start_idx, color='blue', linestyle='-.')
ax.text(start_idx, max_y*1.0, "Work Start", color='blue', ha='center', bbox=bbox)

gate_colors = {"FDG": "purple", "C-Build": "#d4af37", "FIG": "brown", "RG": "black", "SOP": "darkblue", "EG": "darkgreen"}
for name, wk in project_milestones.items():
    if wk in res_df['Week'].values:
        idx = res_df[res_df['Week'] == wk].index[0]
        c = gate_colors.get(name, 'black')
        ax.axvline(idx, color=c, linestyle='-.')
        ax.text(idx, max_y*0.85, f" {name} ", color=c, rotation=90, bbox=bbox)

# --- DETAILED HIGH-VISIBILITY METRIC ANNOTATIONS AND SPAN LINES ---
y_positions = [0.65, 0.45, 0.25] 
target_milestones = [("RG", rg_week), ("SOP", sop_week), ("EG", eg_week)]

prev_idx = start_idx
prev_comp = 0 
span_y_level = max_y * (1.15 + 0.05 * ui_truck_count) 

for i, (m_name, m_wk) in enumerate(target_milestones):
    idx, comp, miss = get_metrics_at_week(m_wk)
    
    if idx is not None:
        phase_sent = comp - prev_comp
        y_pos = max_y * y_positions[i]
        
        safe_total = max(1, total_scope)
        sent_pct = (comp / safe_total) * 100
        miss_pct = (miss / safe_total) * 100
        
        if miss > 0.5:
            bg_color = "#dc3545" 
        else:
            bg_color = "#28a745" 
            
        box_text = f" {m_name} Status \n Sent: {int(comp)} ({sent_pct:.1f}%) \n Missed: {int(miss)} ({miss_pct:.1f}%) "
        
        ax.annotate(box_text, xy=(idx, 0), xytext=(idx - max(2, len(res_df)*0.03), y_pos),
                    arrowprops=dict(facecolor=bg_color, edgecolor='none', shrink=0.05, width=2.5, headwidth=8),
                    fontsize=12, fontweight='bold', color='white',
                    bbox=dict(boxstyle="round,pad=0.5", fc=bg_color, ec='none', alpha=0.95))
        
        if prev_idx < idx:
            ax.annotate('', xy=(prev_idx, span_y_level), xytext=(idx, span_y_level),
                        arrowprops=dict(arrowstyle='<->', color='#555555', lw=1.5))
            
            mid_x = (prev_idx + idx) / 2
            ax.text(mid_x, span_y_level + (max_y*0.015), f"{int(phase_sent)} IH", 
                    ha='center', va='bottom', fontsize=10, fontweight='bold', color='#333333',
                    bbox=dict(boxstyle="round,pad=0.2", fc="#fdfdfd", ec="#cccccc", alpha=0.95))
        
        prev_idx = idx
        prev_comp = comp

ax.set_ylabel("Infoheaders")
ax.grid(True, alpha=0.3)
ax.legend(loc='upper left')
step = 2 if len(res_df) < 80 else 4
ax.set_xticks(res_df['Index'][::step])
ax.set_xticklabels(res_df['Week_Str'][::step], rotation=90)

st.pyplot(fig)

# --- EXPANDED METRICS PANEL ---
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Scope", f"{int(total_scope)}")

def format_missed_label(miss_val):
    if miss_val > 0.5:
        return f"❌ {int(miss_val)} Missed"
    return "✅ 0 Missed"

_, comp_rg, miss_rg = get_metrics_at_week(rg_week)
_, comp_sop, miss_sop = get_metrics_at_week(sop_week)
_, comp_eg, miss_eg = get_metrics_at_week(eg_week)

phase_rg = comp_rg
phase_sop = comp_sop - comp_rg
phase_eg = comp_eg - comp_sop

c2.metric("Status at RG", format_missed_label(miss_rg), f"Total Sent: {int(comp_rg)} (+{int(phase_rg)} Phase)", delta_color="off")
c3.metric("Status at SOP", format_missed_label(miss_sop), f"Total Sent: {int(comp_sop)} (+{int(phase_sop)} Phase)", delta_color="off")
c4.metric("Status at EG", format_missed_label(miss_eg), f"Total Sent: {int(comp_eg)} (+{int(phase_eg)} Phase)", delta_color="off")

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
