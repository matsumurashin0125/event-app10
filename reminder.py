from main import app, send_reminder_for_tomorrow

if __name__ == "__main__":
    with app.app_context():
        send_reminder_for_tomorrow()
