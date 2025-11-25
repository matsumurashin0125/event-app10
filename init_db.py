# init_db.py
from main import create_app
from models import db

app = create_app()

with app.app_context():
    print("Creating PostgreSQL tables...")
    db.create_all()
    print("Done.")