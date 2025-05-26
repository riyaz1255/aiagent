from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from twilio.twiml.messaging_response import MessagingResponse
import uuid
import psycopg2
import os

app = Flask(__name__)

# PostgreSQL connection (read from env vars)
conn = psycopg2.connect(
    dbname=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASS'),
    host=os.getenv('DB_HOST'),
    port=os.getenv('DB_PORT')
)
cursor = conn.cursor()

# Create necessary tables if not exist
cursor.execute('''
    CREATE TABLE IF NOT EXISTS appointments (
        id UUID PRIMARY KEY,
        phone TEXT,
        name TEXT,
        slot TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS followups (
        id UUID PRIMARY KEY,
        appointment_id UUID,
        reminder_sent TIMESTAMP,
        status TEXT DEFAULT 'pending'
    );
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS conversation_state (
        phone TEXT PRIMARY KEY,
        last_step TEXT,
        selected_slot TEXT
    );
''')
conn.commit()

available_slots = ["10:00 AM", "11:00 AM", "12:00 PM", "02:00 PM", "03:00 PM", "04:00 PM"]

@app.route("/whatsapp_webhook", methods=["POST"])
def whatsapp_webhook():
    incoming_data = request.form
    message = incoming_data.get('Body', '').strip().lower()
    phone = incoming_data.get('From').split(':')[-1]
    name = "Patient"

    cursor.execute("SELECT last_step FROM conversation_state WHERE phone = %s", (phone,))
    state = cursor.fetchone()
    last_step = state[0] if state else None

    response = MessagingResponse()

    if message == 'hi' or not last_step:
        cursor.execute("DELETE FROM conversation_state WHERE phone = %s", (phone,))
        cursor.execute("INSERT INTO conversation_state (phone, last_step) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET last_step = EXCLUDED.last_step", (phone, 'greeting'))
        conn.commit()
        response.message("Hello! Welcome to ABC Clinic. Please choose:\n1. Book Appointment\n2. Reschedule\n3. Follow-up Reminder")

    elif last_step == 'greeting' and message == '1':
        cursor.execute("UPDATE conversation_state SET last_step = %s WHERE phone = %s", ('choosing_slot', phone))
        conn.commit()
        slot_text = "\n".join(available_slots)
        response.message(f"Please choose a slot:\n{slot_text}")

    elif last_step == 'choosing_slot':
        slot = message.upper()
        if slot in available_slots:
            appt_id = str(uuid.uuid4())
            cursor.execute("INSERT INTO appointments (id, phone, name, slot) VALUES (%s, %s, %s, %s)", (appt_id, phone, name, slot))
            available_slots.remove(slot)
            cursor.execute("DELETE FROM conversation_state WHERE phone = %s", (phone,))
            conn.commit()
            response.message(f"Appointment booked at {slot}. Thank you!")
        else:
            response.message("Slot not available or invalid. Please choose a valid slot.")

    else:
        response.message("Sorry, I didn't understand that. Please type 'hi' to start again.")

    return str(response)

@app.route("/schedule_followups", methods=['GET'])
def schedule_followups():
    cursor.execute("SELECT id, phone FROM appointments WHERE created_at <= NOW() - INTERVAL '1 day'")
    appts = cursor.fetchall()
    for appt in appts:
        followup_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO followups (id, appointment_id, reminder_sent) VALUES (%s, %s, %s)", (followup_id, appt[0], datetime.now()))
    conn.commit()
    return jsonify({"status": "success", "message": f"Scheduled {len(appts)} follow-ups."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
