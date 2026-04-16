# --- Simulation Loop ---
data = []
backlog = 0

if pure_capacity_mode:
    # -----------------------------------------------------
    # MODE A: PURE CAPACITY (SE Count is the only constraint)
    # -----------------------------------------------------
    for i in range(len(df)):
        # Dump the entire total_scope into the backlog at the start index
        new_work = total_scope if i == start_idx else 0
        
        pool = new_work + backlog
        processed = min(pool, max_capacity)
        backlog = pool - processed
        
        data.append({"Index": i, "Gen": new_work, "Sent": processed, "Backlog": backlog})

else:
    # -----------------------------------------------------
    # MODE B: TRUCK SCHEDULE (Time is a constraint)
    # -----------------------------------------------------
    for i in range(len(df)):
        new_work = 0
        
        if i >= start_idx and i < first_arrival_idx:
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

# Track cumulative sent infoheaders
res_df['Cumulative_Sent'] = res_df['Sent'].cumsum()
