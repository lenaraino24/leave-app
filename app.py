import streamlit as st
import pandas as pd
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# ==========================================
# 📧 SECURE EMAIL CONFIGURATION (Using Streamlit Secrets)
# ==========================================
try:
    SENDER_EMAIL = st.secrets["SENDER_EMAIL"]
    SENDER_PASSWORD = st.secrets["SENDER_PASSWORD"]
except Exception:
    SENDER_EMAIL = None
    SENDER_PASSWORD = None

def send_email_notification(to_email, subject, body):
    """Sends an email notification using Gmail's SMTP server."""
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

# ==========================================
# 🗄️ DATABASE SETUP
# ==========================================
DB_FILE = "leave_system.db"
EXCEL_FILE = "employees.xlsx"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Table for employees
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            Employee_ID TEXT PRIMARY KEY,
            Full_Name TEXT,
            Email TEXT,
            Monthly_Salary REAL,
            Department TEXT,
            Manager_Name TEXT,
            Manager_Email TEXT,
            Sick_Balance INTEGER,
            Annual_Balance INTEGER,
            Casual_Balance INTEGER
        )
    ''')
    
    # Table for leave requests
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leave_requests (
            Request_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            Employee_ID TEXT,
            Employee_Name TEXT,
            Leave_Type TEXT,
            Duration INTEGER,
            Status TEXT,
            Feedback TEXT,
            FOREIGN KEY (Employee_ID) REFERENCES employees (Employee_ID)
        )
    ''')
    conn.commit()
    conn.close()

def sync_excel_with_db():
    if not os.path.exists(EXCEL_FILE):
        st.error(f"Error: {EXCEL_FILE} not found. Please verify it is uploaded to your GitHub repository.")
        st.stop()
        
    df = pd.read_excel(EXCEL_FILE)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get existing DB users to prevent wiping updated balances
    cursor.execute("SELECT Employee_ID FROM employees")
    existing_ids = {row[0] for row in cursor.fetchall()}
    
    for _, row in df.iterrows():
        emp_id = str(row['Employee_ID']).strip()
        if emp_id not in existing_ids:
            cursor.execute('''
                INSERT INTO employees (
                    Employee_ID, Full_Name, Email, Monthly_Salary, Department, 
                    Manager_Name, Manager_Email, Sick_Balance, Annual_Balance, Casual_Balance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                emp_id, row['Full_Name'], row['Email'], row['Monthly_Salary'], row['Department'],
                row['Manager_Name'], row['Manager_Email'], int(row['Initial_Sick_Balance']), 
                int(row['Initial_Annual_Balance']), int(row['Initial_Casual_Balance'])
            ))
    conn.commit()
    conn.close()

# Force-initialize databases before Streamlit starts rendering
init_db()
sync_excel_with_db()

# ==========================================
# 💻 STREAMLIT INTERFACE
# ==========================================
st.set_page_config(page_title="Corporate Leave Management System", page_icon="🌴", layout="centered")
st.title("🌴 Corporate Leave Management System")

# Session state initialization
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None

# Log out mechanism
def logout():
    st.session_state.logged_in = False
    st.session_state.user = None
    st.rerun()

# ----------------- LOGIN PAGE -----------------
if not st.session_state.logged_in:
    st.subheader("🔑 Sign In Portal")
    email_input = st.text_input("Enter your corporate email address:").strip().lower()
    
    if st.button("Log In"):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM employees WHERE LOWER(Email) = ?", (email_input,))
        user_row = cursor.fetchone()
        conn.close()
        
        if user_row:
            st.session_state.logged_in = True
            st.session_state.user = {
                "Employee_ID": user_row[0],
                "Full_Name": user_row[1],
                "Email": user_row[2],
                "Department": user_row[4],
                "Manager_Name": user_row[5],
                "Manager_Email": user_row[6],
                "Sick_Balance": user_row[7],
                "Annual_Balance": user_row[8],
                "Casual_Balance": user_row[9],
            }
            st.rerun()
        else:
            st.error("Error: This email address was not found in the Master Employee Registry.")

# ----------------- PORTAL CONTENT -----------------
else:
    user = st.session_state.user
    
    # Check if the user is a manager of someone else
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM employees WHERE LOWER(Manager_Email) = ?", (user['Email'].lower(),))
    is_manager = cursor.fetchone()[0] > 0
    conn.close()
    
    col1, col2 = st.columns([4, 1])
    with col1:
        st.write(f"Logged in as: **{user['Full_Name']}** ({user['Department']})")
    with col2:
        if st.button("Log Out"):
            logout()
            
    view_option = "My Personal Portal"
    if is_manager:
        view_option = st.selectbox("Go to:", ["My Personal Portal", "Manager Dashboard"])
        
    st.markdown("---")

    # 1. EMPLOYEE VIEW
    if view_option == "My Personal Portal":
        st.subheader("📊 Your Remaining Leave Balances")
        
        # Get fresh balances from DB
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT Sick_Balance, Annual_Balance, Casual_Balance FROM employees WHERE Employee_ID = ?", (user['Employee_ID'],))
        balances = cursor.fetchone()
        conn.close()
        
        b1, b2, b3 = st.columns(3)
        b1.metric("🤒 Sick Leave", f"{balances[0]} days")
        b2.metric("✈️ Annual Leave", f"{balances[1]} days")
        b3.metric("🏡 Casual Leave", f"{balances[2]} days")
        
        st.write("---")
        
        # Submit Leave
        st.subheader("📝 Submit a New Request")
        leave_type = st.selectbox("Select Leave Type:", ["Sick Leave", "Annual Leave", "Casual Leave"])
        duration = st.number_input("Type number of days requested:", min_value=1, max_value=30, value=1, step=1)
        reason = st.text_area("Reason for leave:", placeholder="Describe why you are taking this time off...")
        
        if st.button("🚀 Submit Request"):
            # Check balance limits
            balance_idx = 0 if leave_type == "Sick Leave" else (1 if leave_type == "Annual Leave" else 2)
            current_balance = balances[balance_idx]
            
            if duration > current_balance:
                st.error(f"Insufficient balance! You only have {current_balance} days left for {leave_type}.")
            else:
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO leave_requests (Employee_ID, Employee_Name, Leave_Type, Duration, Status, Feedback)
                    VALUES (?, ?, ?, ?, 'Pending', '')
                ''', (user['Employee_ID'], user['Full_Name'], leave_type, duration))
                conn.commit()
                conn.close()
                
                # 📧 SEND EMAIL TO THE MANAGER
                if user['Manager_Email']:
                    email_subject = f"📋 Action Required: New Leave Request from {user['Full_Name']}"
                    email_body = (
                        f"Hello {user['Manager_Name']},\n\n"
                        f"{user['Full_Name']} has submitted a request for leave:\n"
                        f"- Type: {leave_type}\n"
                        f"- Duration: {duration} day(s)\n"
                        f"- Reason: \"{reason}\"\n\n"
                        f"Please log into the Leave Management Portal to review this application.\n\n"
                        f"Best regards,\n"
                        f"Corporate HR System"
                    )
                    sent = send_email_notification(user['Manager_Email'], email_subject, email_body)
                    if sent:
                        st.success(f"Request submitted! An email notification has been sent to your manager ({user['Manager_Email']}).")
                    else:
                        st.warning("Request submitted successfully! Set up your Streamlit Secrets to enable email notifications.")
                else:
                    st.success("Request submitted successfully!")
                
                st.rerun()

        # History table
        st.write("---")
        st.subheader("🕒 My Request History")
        
        # Ensure database tables are strictly verified before calling pd.read_sql_query
        init_db()
        
        conn = sqlite3.connect(DB_FILE)
        history_df = pd.read_sql_query("SELECT Request_ID, Leave_Type, Duration, Status, Feedback FROM leave_requests WHERE Employee_ID = ?", conn, params=(user['Employee_ID'],))
        conn.close()
        st.dataframe(history_df, use_container_width=True)

    # 2. MANAGER VIEW
    elif view_option == "Manager Dashboard":
        st.subheader("📥 Incoming Requests Pending Your Decision")
        
        init_db()
        conn = sqlite3.connect(DB_FILE)
        # Fetch pending requests submitted by employees managed by this user
        cursor = conn.cursor()
        cursor.execute('''
            SELECT r.Request_ID, r.Employee_Name, r.Leave_Type, r.Duration, r.Employee_ID, e.Email
            FROM leave_requests r
            JOIN employees e ON r.Employee_ID = e.Employee_ID
            WHERE LOWER(e.Manager_Email) = ? AND r.Status = 'Pending'
        ''', (user['Email'].lower(),))
        pending_requests = cursor.fetchall()
        conn.close()
        
        if len(pending_requests) == 0:
            st.info("You have no pending leave requests to approve!")
        else:
            for req in pending_requests:
                req_id, emp_name, l_type, dur, emp_id, emp_email = req
                
                with st.container():
                    st.write(f"**{emp_name}** requested **{dur} days** of **{l_type}**.")
                    feedback_val = st.text_input(f"Manager Remarks for Request #{req_id}:", key=f"feed_{req_id}", placeholder="Good luck! / Approved.")
                    
                    col_app, col_rej, _ = st.columns([1, 1, 4])
                    
                    if col_app.button("✅ Approve", key=f"app_{req_id}"):
                        conn = sqlite3.connect(DB_FILE)
                        cursor = conn.cursor()
                        # Deduct balance
                        balance_col = "Sick_Balance" if l_type == "Sick Leave" else ("Annual_Balance" if l_type == "Annual Leave" else "Casual_Balance")
                        cursor.execute(f"UPDATE employees SET {balance_col} = {balance_col} - ? WHERE Employee_ID = ?", (dur, emp_id))
                        # Set status
                        cursor.execute("UPDATE leave_requests SET Status = 'Approved', Feedback = ? WHERE Request_ID = ?", (feedback_val, req_id))
                        conn.commit()
                        conn.close()
                        
                        # 📧 SEND EMAIL TO EMPLOYEE
                        email_subject = "🎉 Update: Your Leave Request has been Approved!"
                        email_body = (
                            f"Hello {emp_name},\n\n"
                            f"Your request for {dur} day(s) of {l_type} has been APPROVED by {user['Full_Name']}.\n"
                            f"Manager's Remarks: \"{feedback_val}\"\n\n"
                            f"Your balances have been successfully updated in the system.\n\n"
                            f"Best regards,\n"
                            f"Corporate HR System"
                        )
                        send_email_notification(emp_email, email_subject, email_body)
                        
                        st.success(f"Request Approved and email sent to {emp_name}!")
                        st.rerun()
                        
                    if col_rej.button("❌ Reject", key=f"rej_{req_id}"):
                        conn = sqlite3.connect(DB_FILE)
                        cursor = conn.cursor()
                        cursor.execute("UPDATE leave_requests SET Status = 'Rejected', Feedback = ? WHERE Request_ID = ?", (feedback_val, req_id))
                        conn.commit()
                        conn.close()
                        
                        # 📧 SEND EMAIL TO EMPLOYEE
                        email_subject = "⚠️ Update: Your Leave Request has been Rejected"
                        email_body = (
                            f"Hello {emp_name},\n\n"
                            f"Your request for {dur} day(s) of {l_type} was not approved by {user['Full_Name']}.\n"
                            f"Manager's Remarks: \"{feedback_val}\"\n\n"
                            f"Please contact your manager directly if you have any questions.\n\n"
                            f"Best regards,\n"
                            f"Corporate HR System"
                        )
                        send_email_notification(emp_email, email_subject, email_body)
                        
                        st.error("Request Rejected and notification sent.")
                        st.rerun()
                st.markdown("---")
