import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import norm

# --- PAGE CONFIG ---
st.set_page_config(page_title="Workpackage Request Estimation", layout="wide")

st.title("🚛 Workpackage Request Estimation")
st.markdown("Use the sidebar to simulate project scope, timeline, and resource bottlenecks.")

# --- SIDEBAR INPUTS ---
st.sidebar.header("1. Scope & Dates")
total_scope = st.sidebar.number_input("Total Infoheaders", value=1500, step=50)
work_start_week = st.sidebar.number_input("Work Start Week (YYWW)", value=2615)
truck_arrival = st.sidebar.number_input("Truck Arrival (YYWW)", value=2625)
truck_departure = st.sidebar.number_input("Truck Departure (YYWW)", value=2737)

st.sidebar.header("2. Work Split")
pre_work_pct = st.sidebar.slider("Pre-Work %", 0.0, 0.5, 0.10)
post_work_pct = st.sidebar.slider("Post-Work %", 0.0, 0.5, 0.10)

st.sidebar.header("3. Resources")
se_count = st.sidebar.number_input("SE Headcount", value=3)
ih_per_se = st.sidebar.number_input("IH per SE/Week", value=5)

st.sidebar.header("4. Milestones")
fdg_week = st.sidebar.number_input("FDG Week", value=2515)
c_build_week = st.sidebar.number_input("C-Build Week", value=2548)
fig_week = st.sidebar.number_input("FIG Week", value=2639)
rg_week = st.sidebar.number_input("RG Deadline", value=2724)

# --- LOGIC ENGINE ---
max_capacity = se_count * ih_per_se
project_milestones = {"FDG": fdg_week, "C-Build": c_build_week, "FIG": fig_week, "RG": rg_week}

# 1. Dynamic Start Date Logic
# Find the absolute earliest date to start the graph
all_input_dates = [work_start_week, truck_arrival, fdg_week, c_build_week, 2530]
earliest_date = min(all_input_dates)

if earliest_date % 100 <= 2:
    start_week = ((earliest_date // 100) - 1) * 100 + 50
else:
    start_week = earliest_date - 2

# 2. Dynamic End Date Logic (THE FIX)
# Find the absolute latest date to end the graph (Truck Dep or RG)
latest_date = max(rg_week, truck_departure)

end_year_diff = (latest_date // 100) - (start_week // 100)
end_week_diff = (latest_date % 100) - (start_week % 100)
total_duration = (end_year_diff * 52) + end_week_diff + 15 # Add 15 weeks buffer
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
    arrival_idx = df[df['Week'] == truck_arrival].index[0]
    depart_idx = df[df['Week'] == truck_departure].index[0]
    rg_idx = df[df['Week'] == rg_week].index[0]
    start_idx = df[df['Week'] == work_start_week].index[0]
    
    truck_center_idx = (arrival_idx + depart_idx) / 2
    sigma_idx = (depart_idx - arrival_idx) / 5
except IndexError:
    st.error(f"⚠️ Date Mismatch: The generated timeline runs from {weeks[0]} to {weeks[-1]}. One of your dates is outside this range.")
    st.stop()

# Flow Calculations
demand_pre = total_scope * pre_work_pct
demand_post = total_scope * post_work_pct
demand_truck = total_scope - (demand_pre + demand_post)

dur_pre = arrival_idx - start_idx
rate_pre = demand_pre / dur_pre if dur_pre > 0 else 0
dur_post = rg_idx - depart_idx
# If truck leaves AFTER RG, post-work rate is 0 or handled differently. 
# Here we clamp it to prevent division by zero or negative time.
if dur_post <= 0:
    rate_post = 0 # Cannot do post-work if truck leaves after deadline
else:
    rate_post = demand_post / dur_post

raw_bell = []
for i in range(len(df)):
    prob = norm.pdf(i, truck_center_idx, sigma_idx) if sigma_idx > 0 else 0
    raw_bell.append(prob)
total_bell = sum(raw_bell)

data = []
backlog = 0
for i in range(len(df)):
    arriving = 0
    if i >= start_idx and i <= arrival_idx: arriving += rate_pre
    # Only add post-work if we are past departure AND before RG
    if i > depart_idx and i <= rg_idx: arriving += rate_post
    if total_bell > 0: arriving += (raw_bell[i] / total_bell) * demand_truck
    
    pool = arriving + backlog
    sent = min(pool, max_capacity)
    backlog = pool - sent
    data.append({"Index": i, "Gen": arriving, "Sent": sent, "Backlog": backlog})

res_df = pd.DataFrame(data)
res_df = res_df.merge(df, left_on='Index', right_on='Index')

# --- PLOTTING ---
fig, ax = plt.subplots(figsize=(16, 7))
ax.bar(res_df['Index'], res_df['Sent'], color='#005f9e', alpha=0.9, label='Team Output')
ax.plot(res_df['Index'], res_df['Gen'], color='#333333', linestyle='--', linewidth=3, label='Work Generated')

max_y = max(res_df['Gen'].max(), max_capacity)
if max_y == 0: max_y = 10 # Prevent flat graph crash
ax.set_ylim(0, max_y * 1.6)

bbox = dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.85)
ax.axvline(start_idx, color='blue', linestyle=':')
ax.text(start_idx, max_y*1.1, f"Start\n{work_start_week}", color='blue', ha='center', bbox=bbox)
ax.axvline(arrival_idx, color='green', linestyle=':')
ax.text(arrival_idx, max_y*1.02, "Arrival", color='green', ha='center', bbox=bbox)
ax.axvline(depart_idx, color='orange', linestyle=':')
ax.text(depart_idx, max_y*1.02, "Departure", color='orange', ha='center', bbox=bbox)

colors = {"FDG": "purple", "C-Build": "#d4af37", "FIG": "brown", "RG": "black"}
for name, wk in project_milestones.items():
    if wk in res_df['Week'].values:
        idx = res_df[res_df['Week'] == wk].index[0]
        c = colors.get(name, 'black')
        ax.axvline(idx, color=c, linestyle='-.')
        ax.text(idx, max_y*0.85, f" {name} ", color=c, rotation=90, bbox=bbox)

missed = res_df[res_df['Week'] == rg_week]['Backlog'].values[0]
if missed > 1:
    ax.annotate(f'MISSED: {int(missed)} IH', xy=(rg_idx, 0), xytext=(rg_idx-5, max_y*0.6),
                arrowprops=dict(facecolor='red', shrink=0.05), fontsize=14, color='white', 
                bbox=dict(boxstyle="round", fc="red"))
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

# --- METRICS ROW ---
m1, m2, m3 = st.columns(3)
m1.metric("Early Work Volume", f"{int(demand_pre)} IH")
m2.metric("Truck Phase Volume", f"{int(demand_truck)} IH")
if missed > 0:
    m3.metric("Missed at RG", f"{int(missed)} IH", delta="Risk", delta_color="inverse")
else:
    m3.metric("Status", "Success", delta="On Track")
