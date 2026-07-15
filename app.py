import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime

# --- CONFIGURATION ---
DB_NAME = "leave_system.db"
EXCEL_NAME = "employees.xlsx"

# Standard list of public holidays to protect employee wages
PUBLIC_HOLIDAYS = [
    "2026-01-01",  # New Year's Day
    "2026-12-02",  # UAE National Day
    "2026-12-03"   # National Day Holiday
]

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            Employee_ID TEXT PRIMARY KEY, Full_Name TEXT, Email TEXT UNIQUE,
            Monthly_Salary REAL, Department TEXT, Manager_Name TEXT, Manager_Email TEXT,
            Sick_Balance REAL, Annual_Balance REAL, Casual_Balance REAL
        )
    ''');
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leave_requests (
            Request_ID INTEGER PRIMARY KEY AUTOINCREMENT, Employee_Email TEXT, Employee_Name TEXT,
            Leave_Type TEXT, Duration INTEGER, Start_Date TEXT, End_Date TEXT,
            Salary_Allocation REAL, Unpaid_Days INTEGER, Manager_Email TEXT, Status TEXT, Feedback TEXT
        )
    ''');
    
    # Sync database with Excel sheet on startup if database is brand new
    cursor.execute("SELECT COUNT(*) FROM employees")
    if cursor.fetchone()[0] == 0 and os.path.exists(EXCEL_NAME):
        df = pd.read_excel(EXCEL_NAME)
        for _, row in df.iterrows():
            cursor.execute('''
                INSERT OR IGNORE INTO employees VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(row['Employee_ID']), row['Full_Name'], row['Email'].strip().lower(),
                row['Monthly_Salary'], row['Department'], row['Manager_Name'], row['Manager_Email'],
                row['Initial_Sick_Balance'], row['Initial_Annual_Balance'], row['Initial_Casual_Balance']
            ))
        conn.commit()
    conn.close()

init_db()

# --- DATABASE ACTIONS ---
def get_user_data(email):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM employees WHERE LOWER(Email) = ?", conn, params=(email.lower(),))
    conn.close()
    return df.iloc[0] if not df.empty else None

def sync_excel_with_db(uploaded_file):
    # Safe sync: Update salaries, managers, departments, and add new hires, but PRESERVE existing leave balances
    df = pd.read_excel(uploaded_file)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for _, row in df.iterrows():
        email = row['Email'].strip().lower()
        cursor.execute("SELECT 1 FROM employees WHERE LOWER(Email) = ?", (email,))
        exists = cursor.fetchone()
        if exists:
            # Update only profile information, do not overwrite their current ongoing leave balances!
            cursor.execute('''
                UPDATE employees SET 
                    Full_Name = ?, Monthly_Salary = ?, Department = ?, 
                    Manager_Name = ?, Manager_Email = ? 
                WHERE LOWER(Email) = ?
            ''', (row['Full_Name'], row['Monthly_Salary'], row['Department'], row['Manager_Name'], row['Manager_Email'], email))
        else:
            # Insert brand new employee with starting balances
            cursor.execute('''
                INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(row['Employee_ID']), row['Full_Name'], email,
                row['Monthly_Salary'], row['Department'], row['Manager_Name'], row['Manager_Email'],
                row['Initial_Sick_Balance'], row['Initial_Annual_Balance'], row['Initial_Casual_Balance']
            ))
    conn.commit()
    conn.close()

# --- STREAMLIT FRONT-END ---
st.set_page_config(page_title="Leave Management System", layout="wide")
st.title("🌴 Corporate Leave Management System")

if 'user_email' not in st.session_state:
    st.session_state.user_email = None

# --- AUTHENTICATION SCREEN ---
if not st.session_state.user_email:
    st.subheader("🔑 Sign In Portal")
    email_input = st.text_input("Enter your corporate email address:").strip().lower()
    if st.button("Log In"):
        user = get_user_data(email_input)
        if user is not None:
            st.session_state.user_email = email_input
            st.rerun()
        else:
            st.error("Error: This email address was not found in the Master Employee Registry.")
else:
    # Fetch logged-in user profile
    user = get_user_data(st.session_state.user_email)
    
    # Determine roles dynamically
    is_manager = not pd.read_sql_query("SELECT 1 FROM employees WHERE LOWER(Manager_Email) = ?", sqlite3.connect(DB_NAME), params=(user['Email'].lower(),)).empty
    is_hr = user['Department'].upper() == "HR"
    
    # Header Navigation
    c_header = st.columns([6, 2, 2, 2])
    c_header[0].write(f"Logged in as: **{user['Full_Name']}** ({user['Department']} Department)")
    
    modes = ["My Personal Portal"]
    if is_manager: modes.append("Manager Dashboard")
    if is_hr: modes.append("HR Administration")
    
    current_mode = c_header[1].selectbox("Go to:", modes)
    
    if c_header[3].button("Log Out"):
        st.session_state.user_email = None
        st.rerun()
        
    st.markdown("---")

    # --- MODE 1: MY PERSONAL PORTAL ---
    if current_mode == "My Personal Portal":
        st.header("👤 My Personal Leave Workspace")
        
        # Display Current Balances
        b_cols = st.columns(3)
        b_cols[0].metric("Annual Leave Balance", f"{user['Annual_Balance']} Days")
        b_cols[1].metric("Sick Leave (Paid Remaining)", f"{user['Sick_Balance']} Days")
        b_cols[2].metric("Casual Leave Balance", f"{user['Casual_Balance']} Days")
        
        st.subheader("📝 Submit a New Request")
        leave_type = st.selectbox("Select Leave Type:", ["Annual Leave", "Sick Leave", "Casual Leave"])
        
        duration = 0
        start_date = None
        end_date = None
        salary_allocation = 0.0
        unpaid_days = 0
        can_submit = True
        
        if leave_type == "Annual Leave":
            d_cols = st.columns(2)
            start_date = d_cols[0].date_input("Start Date", datetime.today())
            end_date = d_cols[1].date_input("End Date", datetime.today())
            
            # Auto-calculate duration from calendar
            duration = (end_date - start_date).days + 1
            st.info(f"🔢 Calculated Duration: **{duration} Calendar Days**")
            
            if duration <= 0:
                st.error("Invalid Dates: End date must be on or after the start date.")
                can_submit = False
            elif duration > user['Annual_Balance']:
                st.error(f"Deduction limit exceeded: Your Annual Leave balance is only {user['Annual_Balance']} days.")
                can_submit = False
            else:
                # Calculate daily rate
                daily_rate = user['Monthly_Salary'] / 30
                salary_allocation = round(duration * daily_rate, 2)
                st.success(f"💰 Projected Paid Allocation: **{salary_allocation} AED**")
                
        elif leave_type in ["Sick Leave", "Casual Leave"]:
            # Direct typing input for short-term leaves
            duration = st.number_input("Type number of days requested:", min_value=1, max_value=30, step=1)
            
            if leave_type == "Casual Leave" and duration > user['Casual_Balance']:
                st.error(f"Blocked: You only have {user['Casual_Balance']} Casual Leave days remaining.")
                can_submit = False
                
            elif leave_type == "Sick Leave" and duration > user['Sick_Balance']:
                # Calculate if any requested days fall under public holiday protection
                unpaid_days = int(duration - user['Sick_Balance'])
                st.warning(f"⚠️ Balance Spillover: {int(user['Sick_Balance'])} days will be Paid. **{unpaid_days} Day(s) will be Unpaid**.")

        reason = st.text_area("Reason for leave:")
        
        if st.button("🚀 Submit Request", disabled=not can_submit):
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO leave_requests (Employee_Email, Employee_Name, Leave_Type, Duration, Start_Date, End_Date, Salary_Allocation, Unpaid_Days, Manager_Email, Status, Feedback)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', '')
            ''', (user['Email'], user['Full_Name'], leave_type, duration, str(start_date), str(end_date), salary_allocation, unpaid_days, user['Manager_Email']))
            conn.commit()
            conn.close()
            st.success("Your request has been successfully sent to your manager!")
            st.rerun()
            
        # Employee personal history
        st.subheader("🕒 My Request History")
        conn = sqlite3.connect(DB_NAME)
        history_df = pd.read_sql_query("SELECT Request_ID, Leave_Type, Duration, Start_Date, End_Date, Status, Feedback FROM leave_requests WHERE Employee_Email = ?", conn, params=(user['Email'].lower(),))
        conn.close()
        if not history_df.empty:
            st.dataframe(history_df, use_container_width=True, hide_index=True)
        else:
            st.info("You have not submitted any leave requests yet.")

    # --- MODE 2: MANAGER WORKSPACE ---
    elif current_mode == "Manager Dashboard":
        st.header("📥 Supervisor Review Panel")
        
        conn = sqlite3.connect(DB_NAME)
        queue = pd.read_sql_query("SELECT * FROM leave_requests WHERE Manager_Email = ? AND Status = 'Pending'", conn, params=(user['Email'].lower(),))
        conn.close()
        
        if not queue.empty:
            for _, req in queue.iterrows():
                with st.expander(f"📋 Request from {req['Employee_Name']} - {req['Leave_Type']} ({req['Duration']} Days)"):
                    st.write(f"**Dates Requested:** {req['Start_Date']} to {req['End_Date']}")
                    if req['Salary_Allocation'] > 0:
                        st.write(f"💵 **Calculated Payout Allocation:** {req['Salary_Allocation']} AED")
                    if req['Unpaid_Days'] > 0:
                        st.write(f"⚠️ **Unpaid Leave Days Flagged:** {req['Unpaid_Days']} Day(s)")
                    st.write(f"**Reason:** {req['Feedback']}")
                    
                    feedback = st.text_input("Approver Comments / Notes:", key=f"feed_{req['Request_ID']}")
                    
                    c1, c2, _ = st.columns([1, 1, 8])
                    if c1.button("✅ Approve", key=f"app_{req['Request_ID']}"):
                        conn = sqlite3.connect(DB_NAME)
                        cursor = conn.cursor()
                        # Deduct balance if approved
                        balance_col = "Annual_Balance" if req['Leave_Type'] == "Annual Leave" else "Sick_Balance" if req['Leave_Type'] == "Sick Leave" else "Casual_Balance"
                        cursor.execute(f"UPDATE employees SET {balance_col} = MAX(0, {balance_col} - ?) WHERE Email = ?", (req['Duration'], req['Employee_Email']))
                        cursor.execute("UPDATE leave_requests SET Status = 'Approved', Feedback = ? WHERE Request_ID = ?", (feedback, req['Request_ID']))
                        conn.commit()
                        conn.close()
                        st.success("Leave Request Approved!")
                        st.rerun()
                        
                    if c2.button("❌ Reject", key=f"rej_{req['Request_ID']}"):
                        conn = sqlite3.connect(DB_NAME)
                        cursor = conn.cursor()
                        cursor.execute("UPDATE leave_requests SET Status = 'Rejected', Feedback = ? WHERE Request_ID = ?", (feedback, req['Request_ID']))
                        conn.commit()
                        conn.close()
                        st.error("Leave Request Declined.")
                        st.rerun()
        else:
            st.success("All caught up! No pending requests require your approval.")

    # --- MODE 3: HR ADMINISTRATION ---
    elif current_mode == "HR Administration":
        st.header("🏢 Global HR Oversight Workspace")
        
        tab1, tab2, tab3 = st.tabs(["Global Audit Log", "Monthly Payroll Exceptions", "Update Master Registry"])
        
        with tab1:
            st.subheader("📋 Unified Corporate Leave Log")
            conn = sqlite3.connect(DB_NAME)
            master_df = pd.read_sql_query("SELECT * FROM leave_requests", conn)
            conn.close()
            if not master_df.empty:
                st.dataframe(master_df, use_container_width=True, hide_index=True)
            else:
                st.info("No corporate leave records found in the database.")
                
        with tab2:
            st.subheader("💰 Monthly Unpaid Leave Deductions")
            conn = sqlite3.connect(DB_NAME)
            all_data = pd.read_sql_query("SELECT * FROM leave_requests WHERE Unpaid_Days > 0 AND Status = 'Approved'", conn)
            conn.close()
            if not all_data.empty:
                st.warning("The approved entries listed below contain unpaid days and require salary deductions:")
                st.dataframe(all_data[['Employee_Name', 'Leave_Type', 'Duration', 'Unpaid_Days', 'Manager_Email']], use_container_width=True, hide_index=True)
            else:
                st.success("Perfect Month! Zero unpaid day deductions flagged across the workforce.")
                
        with tab3:
            st.subheader("🔄 Update Corporate Directory")
            st.write("Upload an updated `employees.xlsx` file below to sync new hires, manager modifications, or salary increases. This will **not** affect existing employee leave balances.")
            uploaded_file = st.file_uploader("Choose Excel File", type=["xlsx"])
            if uploaded_file is not None:
                sync_excel_with_db(uploaded_file)
                st.success("Employee master directory synced successfully!")