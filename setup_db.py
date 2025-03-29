import sqlite3

# Connect to SQLite
conn = sqlite3.connect("traffic.db")
cursor = conn.cursor()

# Create Traffic Data Table
cursor.execute("""
CREATE TABLE IF NOT EXISTS traffic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location TEXT,
    vehicle_count INTEGER,
    congestion_level TEXT,
    pedestrian_count INTEGER,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()
conn.close()
print("✅ Database setup complete! Run app.py next.")