from flask import Flask, render_template, jsonify, request, session, redirect, url_for, make_response, flash
from utils import send_otp_email
import logging
import secrets
import random
import smtplib
from email.message import EmailMessage
import datetime
import time
import os
import sqlite3
import speech_recognition as sr
from gtts import gTTS
from dotenv import load_dotenv
import hashlib
import string
from contextlib import closing

# Ensure template folder is correctly specified
app = Flask(__name__, template_folder="templates")
app.secret_key = "app_secret_key"

# Initialize database with users, traffic, accidents, and alerts tables
def init_db():
    conn = sqlite3.connect("traffic.db")
    cursor = conn.cursor()
    
    # Create traffic table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS traffic (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location TEXT,
            vehicle_count INTEGER,
            congestion_level TEXT,
            pedestrian_count INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create accidents table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location TEXT,
            description TEXT,
            severity TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create alerts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            location TEXT,
            description TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Add default admin and user
    cursor.execute("SELECT * FROM users WHERE username='admin'")
    if not cursor.fetchone():
        hashed_password = hashlib.sha256("admin123".encode()).hexdigest()
        cursor.execute("INSERT INTO users (username, password, email, role) VALUES (?, ?, ?, ?)",
                       ("admin", hashed_password, "admin@example.com", "admin"))
    
    cursor.execute("SELECT * FROM users WHERE username='user'")
    if not cursor.fetchone():
        hashed_password = hashlib.sha256("user123".encode()).hexdigest()
        cursor.execute("INSERT INTO users (username, password, email, role) VALUES (?, ?, ?, ?)",
                       ("user", hashed_password, "user@example.com", "user"))
    
    conn.commit()
    conn.close()

# Call init_db at app startup
init_db()

# Load environment variables
load_dotenv(dotenv_path="main.env")

# Function to send OTP email
def send_otp_email(receiver_email, otp):
    try:
        EMAIL_ADDRESS = os.getenv("USER_EMAIL_ADDRESS")
        EMAIL_PASSWORD = os.getenv("USER_EMAIL_PASSWORD")

        msg = EmailMessage()
        msg['Subject'] = 'Your OTP for Password Recovery'
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = receiver_email
        msg.set_content(f"Your OTP is: {otp} (valid for 10 minutes)")

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"Error sending OTP email: {e}")
        raise e

# Function to send temporary password email
def send_temp_password_email(receiver_email, temp_password):
    try:
        EMAIL_ADDRESS = os.getenv("USER_EMAIL_ADDRESS")
        EMAIL_PASSWORD = os.getenv("USER_EMAIL_PASSWORD")

        msg = EmailMessage()
        msg['Subject'] = 'Your Temporary Password'
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = receiver_email
        msg.set_content(f"Your temporary password is: {temp_password}\nPlease log in and change it immediately within 10 minutes.")

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"Error sending temporary password email: {e}")
        raise e

# Generate Temporary Password
def generate_temp_password(length=10):
    # Define allowed characters: uppercase, lowercase, digits, and @, #
    characters = string.ascii_uppercase + string.ascii_lowercase + string.digits + '@#'
    # Ensure the password is random and meets the length requirement
    return ''.join(random.choices(characters, k=length))


# Update Temporary Password in Database with return value
def update_temp_password(username, temp_password):
    """
    Updates the user's password in the database with a new temporary password.
    
    Args:
        username (str): The username of the user whose password is to be updated.
        temp_password (str): The new temporary password to set.
    
    Returns:
        bool: True if the password was updated successfully, False otherwise.
    """
    if not username or not temp_password:
        print(f"Invalid input: username={username}, temp_password={temp_password}")
        return False

    hashed_temp_password = hashlib.sha256(temp_password.encode()).hexdigest()
    
    try:
        # Use closing() to ensure the connection is closed even if an error occurs
        with closing(sqlite3.connect("traffic.db")) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute("UPDATE users SET password=? WHERE username=?", 
                              (hashed_temp_password, username))
                affected_rows = cursor.rowcount
                conn.commit()
                if affected_rows > 0:
                    print(f"Password updated successfully for username: {username}")
                    return True
                else:
                    print(f"No user found with username: {username}")
                    return False
    except sqlite3.Error as e:
        print(f"Database error in update_temp_password: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error in update_temp_password: {e}")
        return False

# Function to generate fake accident data
def get_fake_accident_data(location=None):
    cuttack_locations = list({
        "Bidanasi": {"vehicle_range": (70, 200), "pedestrian_range": (40, 110), "congestion": ["Moderate", "High"]},
        "CDA Sector-6": {"vehicle_range": (80, 220), "pedestrian_range": (45, 120), "congestion": ["Low", "Moderate"]},
        "CDA Sector-7": {"vehicle_range": (75, 210), "pedestrian_range": (40, 115), "congestion": ["Low", "Moderate"]},
        "CDA Sector-9": {"vehicle_range": (85, 230), "pedestrian_range": (50, 125), "congestion": ["Low", "Moderate"]},
        "Tulsipur": {"vehicle_range": (65, 190), "pedestrian_range": (35, 100), "congestion": ["Moderate", "High"]},
        "Buxi Bazaar": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["High", "Very High"]},
        "Chandni Chowk": {"vehicle_range": (55, 170), "pedestrian_range": (25, 85), "congestion": ["High", "Very High"]},
        "Mahima Nagar": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Ranihat": {"vehicle_range": (70, 200), "pedestrian_range": (35, 95), "congestion": ["Moderate", "High"]},
        "Badambadi": {"vehicle_range": (90, 250), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Link Road": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Sutahat": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["High", "Very High"]},
        "Jobra": {"vehicle_range": (80, 220), "pedestrian_range": (40, 110), "congestion": ["Moderate", "High"]},
        "Mangalabag": {"vehicle_range": (75, 200), "pedestrian_range": (40, 100), "congestion": ["Moderate", "High"]},
        "Dolamundai": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["High", "Very High"]},
        "Khan Nagar": {"vehicle_range": (70, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Professor Para": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["Low", "Moderate"]},
        "Gandarpur": {"vehicle_range": (85, 230), "pedestrian_range": (50, 120), "congestion": ["Moderate", "High"]},
        "Nayabazar": {"vehicle_range": (70, 200), "pedestrian_range": (35, 100), "congestion": ["High", "Very High"]},
        "Chauliaganj": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Moderate", "High"]},
        "Kathajodi Road": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Telenga Bazar": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["High", "Very High"]},
        "Mal Godown": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Moderate", "High"]},
        "Barabati": {"vehicle_range": (90, 240), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Cantonment Road": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Low", "Moderate"]},
        "Puri Ghat": {"vehicle_range": (55, 170), "pedestrian_range": (25, 85), "congestion": ["Moderate", "High"]},
        "Dargha Bazar": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["High", "Very High"]},
        "Jagatpur": {"vehicle_range": (100, 280), "pedestrian_range": (55, 140), "congestion": ["Low", "Moderate"]},
        "Nimpur": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Low", "Moderate"]},
        "Phulnakhara": {"vehicle_range": (90, 250), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Trisulia": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Low", "Moderate"]},
        "Niali Road": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Choudwar": {"vehicle_range": (95, 260), "pedestrian_range": (50, 135), "congestion": ["Moderate", "High"]},
        "Athagarh": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Low", "Moderate"]},
        "Narasinghpur": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Kakhadi": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Salepur": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Kendrapara Road": {"vehicle_range": (90, 240), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Mahanga": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Pattamundai": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Moderate", "High"]},
        "Banki": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Madhupatna": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Kalyan Nagar": {"vehicle_range": (70, 200), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Nuapatna": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Sikharpur": {"vehicle_range": (75, 210), "pedestrian_range": (40, 110), "congestion": ["Moderate", "High"]},
        "Gopalpur": {"vehicle_range": (80, 220), "pedestrian_range": (45, 115), "congestion": ["Low", "Moderate"]},
        "Balikuda": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Kandarpur": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Tangi": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["Low", "Moderate"]},
        "Nischintakoili": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Moderate", "High"]},
        "Balisahi": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Raghunathpur": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Kuanpal": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Nemalo": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Low", "Moderate"]},
        "Charbatia": {"vehicle_range": (90, 250), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Kapaleswar": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Biribati": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Sankhatras": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Devi Ghat": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["Moderate", "High"]},
        "Harirajpur": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Gadgadia Ghat": {"vehicle_range": (55, 170), "pedestrian_range": (25, 85), "congestion": ["Moderate", "High"]},
        "Chhatia": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Low", "Moderate"]},
        "Bhadimula": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Khandeita": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Sungra": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Chhagaon": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Khandol": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Raisunguda": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Moderate", "High"]},
        "Manijanga": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]}
    }.keys())
    
    if not location:
        location = random.choice(cuttack_locations)
    
    severities = ["Minor", "Moderate", "Severe"]
    descriptions = [
        f"Collision involving {random.randint(2, 5)} vehicles",
        "Pedestrian accident near main road",
        f"Truck overturned on {random.choice(['Highway', 'Expressway', 'Ring Road'])}",
        "Motorcycle crash causing traffic delay",
        "Multi-car pileup due to fog"
    ]
    
    return {
        "location": location,
        "description": random.choice(descriptions),
        "severity": random.choice(severities)
    }

# Function to store accident data
def store_accident_data(location, description, severity):
    conn = sqlite3.connect("traffic.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO accidents (location, description, severity) VALUES (?, ?, ?)", 
                   (location, description, severity))
    conn.commit()
    conn.close()

# Function to generate and store various alerts
def generate_and_store_alert(location=None):
    alert_types = ["accident", "road_work", "weather"]
    type = random.choice(alert_types)
    
    cuttack_locations = list({
        "Bidanasi": {"vehicle_range": (70, 200), "pedestrian_range": (40, 110), "congestion": ["Moderate", "High"]},
        "CDA Sector-6": {"vehicle_range": (80, 220), "pedestrian_range": (45, 120), "congestion": ["Low", "Moderate"]},
        "CDA Sector-7": {"vehicle_range": (75, 210), "pedestrian_range": (40, 115), "congestion": ["Low", "Moderate"]},
        "CDA Sector-9": {"vehicle_range": (85, 230), "pedestrian_range": (50, 125), "congestion": ["Low", "Moderate"]},
        "Tulsipur": {"vehicle_range": (65, 190), "pedestrian_range": (35, 100), "congestion": ["Moderate", "High"]},
        "Buxi Bazaar": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["High", "Very High"]},
        "Chandni Chowk": {"vehicle_range": (55, 170), "pedestrian_range": (25, 85), "congestion": ["High", "Very High"]},
        "Mahima Nagar": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Ranihat": {"vehicle_range": (70, 200), "pedestrian_range": (35, 95), "congestion": ["Moderate", "High"]},
        "Badambadi": {"vehicle_range": (90, 250), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Link Road": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Sutahat": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["High", "Very High"]},
        "Jobra": {"vehicle_range": (80, 220), "pedestrian_range": (40, 110), "congestion": ["Moderate", "High"]},
        "Mangalabag": {"vehicle_range": (75, 200), "pedestrian_range": (40, 100), "congestion": ["Moderate", "High"]},
        "Dolamundai": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["High", "Very High"]},
        "Khan Nagar": {"vehicle_range": (70, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Professor Para": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["Low", "Moderate"]},
        "Gandarpur": {"vehicle_range": (85, 230), "pedestrian_range": (50, 120), "congestion": ["Moderate", "High"]},
        "Nayabazar": {"vehicle_range": (70, 200), "pedestrian_range": (35, 100), "congestion": ["High", "Very High"]},
        "Chauliaganj": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Moderate", "High"]},
        "Kathajodi Road": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Telenga Bazar": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["High", "Very High"]},
        "Mal Godown": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Moderate", "High"]},
        "Barabati": {"vehicle_range": (90, 240), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Cantonment Road": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Low", "Moderate"]},
        "Puri Ghat": {"vehicle_range": (55, 170), "pedestrian_range": (25, 85), "congestion": ["Moderate", "High"]},
        "Dargha Bazar": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["High", "Very High"]},
        "Jagatpur": {"vehicle_range": (100, 280), "pedestrian_range": (55, 140), "congestion": ["Low", "Moderate"]},
        "Nimpur": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Low", "Moderate"]},
        "Phulnakhara": {"vehicle_range": (90, 250), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Trisulia": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Low", "Moderate"]},
        "Niali Road": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Choudwar": {"vehicle_range": (95, 260), "pedestrian_range": (50, 135), "congestion": ["Moderate", "High"]},
        "Athagarh": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Low", "Moderate"]},
        "Narasinghpur": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Kakhadi": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Salepur": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Kendrapara Road": {"vehicle_range": (90, 240), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Mahanga": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Pattamundai": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Moderate", "High"]},
        "Banki": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Madhupatna": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Kalyan Nagar": {"vehicle_range": (70, 200), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Nuapatna": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Sikharpur": {"vehicle_range": (75, 210), "pedestrian_range": (40, 110), "congestion": ["Moderate", "High"]},
        "Gopalpur": {"vehicle_range": (80, 220), "pedestrian_range": (45, 115), "congestion": ["Low", "Moderate"]},
        "Balikuda": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Kandarpur": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Tangi": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["Low", "Moderate"]},
        "Nischintakoili": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Moderate", "High"]},
        "Balisahi": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Raghunathpur": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Kuanpal": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Nemalo": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Low", "Moderate"]},
        "Charbatia": {"vehicle_range": (90, 250), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Kapaleswar": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Biribati": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Sankhatras": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Devi Ghat": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["Moderate", "High"]},
        "Harirajpur": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Gadgadia Ghat": {"vehicle_range": (55, 170), "pedestrian_range": (25, 85), "congestion": ["Moderate", "High"]},
        "Chhatia": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Low", "Moderate"]},
        "Bhadimula": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Khandeita": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Sungra": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Chhagaon": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Khandol": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Raisunguda": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Moderate", "High"]},
        "Manijanga": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]}
    }.keys())
    
    if not location:
        location = random.choice(cuttack_locations)
    
    if type == "accident":
        descriptions = [
            f"Collision involving {random.randint(2, 5)} vehicles",
            "Pedestrian accident near main road",
            f"Truck overturned on {random.choice(['Highway', 'Expressway', 'Ring Road'])}",
            "Motorcycle crash causing traffic delay",
            "Multi-car pileup due to fog"
        ]
    elif type == "road_work":
        descriptions = [
            f"Road work on {location} between {random.randint(1, 10)}th and {random.randint(11, 20)}th Avenue",
            f"Bridge maintenance near {location}",
            f"Construction on {random.choice(['Highway', 'Main Street'])} in {location}",
            "Pothole repairs causing lane closure"
        ]
    elif type == "weather":
        descriptions = [
            "Rain expected this evening - prepare for slower traffic",
            "Fog reducing visibility this morning",
            "Strong winds affecting driving conditions",
            "Heavy rain forecast for the afternoon"
        ]
    description = random.choice(descriptions)
    
    conn = sqlite3.connect("traffic.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO alerts (type, location, description) VALUES (?, ?, ?)", 
                   (type, location, description))
    conn.commit()
    conn.close()
    
    return {"type": type, "location": location, "description": description}

# Logging setup
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@app.route("/admin", methods=["GET"])
def admin_login():
    return render_template("admin_login.html")


@app.route("/admin/login", methods=["POST"])
def admin_login_post():
    username = request.form.get("username")
    password = request.form.get("password")
    hashed_password = hashlib.sha256(password.encode()).hexdigest()

    with sqlite3.connect("traffic.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM users 
            WHERE username=? AND password=? AND role='admin'
        """, (username, hashed_password))
        admin = cursor.fetchone()

    if admin:
        session["admin"] = True
        session["admin_username"] = username
        return redirect("/admin/dashboard")
    else:
        error_message = "❌ Invalid credentials. Please try again."
        return render_template("admin_login.html", error=error_message)


@app.route("/admin/register", methods=["GET", "POST"])
def admin_register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        # ✅ Server-side password confirmation check
        if password != confirm_password:
            error_message = "❌ Passwords do not match."
            return render_template("admin_register.html", error=error_message)

        hashed_password = hashlib.sha256(password.encode()).hexdigest()

        try:
            with sqlite3.connect("traffic.db") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (username, password, email, role)
                    VALUES (?, ?, ?, 'admin')
                """, (username, hashed_password, email))
                conn.commit()

            success_message = "✅ Registration successful! Please login."
            return render_template("admin_login.html", success=success_message)

        except sqlite3.IntegrityError:
            error_message = "❌ Username or email already exists."
            return render_template("admin_register.html", error=error_message)

    return render_template("admin_register.html")



@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect("/admin")

    with sqlite3.connect("traffic.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM traffic ORDER BY id DESC LIMIT 20")
        traffic_data = cursor.fetchall()
        cursor.execute("SELECT * FROM accidents ORDER BY id DESC LIMIT 20")
        accidents = cursor.fetchall()
        cursor.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 20")
        alerts = cursor.fetchall()

    return render_template("admin_dashboard.html", traffic_data=traffic_data, accidents=accidents, alerts=alerts)


@app.route("/admin/delete/<int:id>")
def admin_delete(id):
    if not session.get("admin"):
        return redirect("/admin")
    with sqlite3.connect("traffic.db") as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM traffic WHERE id=?", (id,))
        conn.commit()
    flash("✅ Traffic entry deleted successfully.", "success")
    return redirect("/admin/dashboard")


@app.route("/admin/delete_accident/<int:id>")
def admin_delete_accident(id):
    if not session.get("admin"):
        return redirect("/admin")
    with sqlite3.connect("traffic.db") as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM accidents WHERE id=?", (id,))
        conn.commit()
    flash("✅ Accident entry deleted successfully.", "success")
    return redirect("/admin/dashboard")


@app.route("/admin/delete_alert/<int:id>")
def admin_delete_alert(id):
    if not session.get("admin"):
        return redirect("/admin")
    with sqlite3.connect("traffic.db") as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM alerts WHERE id=?", (id,))
        conn.commit()
    flash("✅ Alert entry deleted successfully.", "success")
    return redirect("/admin/dashboard")


@app.route("/admin/users")
def admin_view_users():
    if not session.get("admin"):
        return redirect("/admin")
    try:
        with sqlite3.connect("traffic.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, email, role, created_at FROM users")
            users = cursor.fetchall()
            logger.debug(f"Retrieved users: {users}")
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return "Database error occurred.", 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return "An unexpected error occurred.", 500

    try:
        return render_template("admin_users.html", users=users)
    except Exception as e:
        logger.error(f"Template rendering error: {e}")
        return "Error rendering template.", 500


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    session.pop("admin_username", None)
    return redirect("/admin")

# -----------------------------
# ✅ Admin Forgot Password Flow
# -----------------------------

@app.route("/admin/forgot_password", methods=["GET", "POST"])
def admin_forgot_password():
    if request.method == "POST":
        email = request.form.get("email")

        with sqlite3.connect("traffic.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM users WHERE email=? AND role='admin'", (email,))
            user = cursor.fetchone()

        if user:
            otp = str(random.randint(100000, 999999))
            session["admin_reset_email"] = email
            session["admin_reset_username"] = user[0]
            session["admin_reset_otp"] = otp
            session["otp_expiry"] = (datetime.datetime.now() + datetime.timedelta(minutes=10)).isoformat()

            send_otp_email(email, otp)
            return redirect(url_for("admin_verify_otp"))
        else:
            error = "No admin found with that email."
            return render_template("admin_forgot_password.html", error=error)

    return render_template("admin_forgot_password.html")


@app.route("/admin/verify_otp", methods=["GET", "POST"])
def admin_verify_otp():
    if request.method == "POST":
        entered_otp = request.form.get("otp")
        expiry = datetime.datetime.fromisoformat(session.get("otp_expiry", "2000-01-01T00:00:00"))
        valid_otp = session.get("admin_reset_otp")

        if not valid_otp or datetime.datetime.now() > expiry:
            session.clear()
            error = "OTP expired or invalid. Please start again."
            return redirect(url_for("admin_forgot_password"))

        if entered_otp != valid_otp:
            error = "Incorrect OTP. Please try again."
            return render_template("admin_verify_otp.html", error=error)

        return redirect(url_for("admin_new_password"))

    return render_template("admin_verify_otp.html")


@app.route("/admin/new_password", methods=["GET", "POST"])
def admin_new_password():
    if request.method == "POST":
        new_password = request.form.get("new_password")
        username = session.get("admin_reset_username")

        if not username:
            error = "Session error. Please restart the reset process."
            return redirect(url_for("admin_forgot_password"))

        if update_temp_password(username, new_password):
            session.clear()
            success = "✅ Password reset successful. Please log in."
            return render_template("admin_login.html", success=success)
        else:
            error = "❌ Failed to reset password."
            return render_template("admin_new_password.html", error=error)

    return render_template("admin_new_password.html")


def update_temp_password(username, password):
    if not username or not password:
        return False

    hashed = hashlib.sha256(password.encode()).hexdigest()

    try:
        with sqlite3.connect("traffic.db") as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password=? WHERE username=?", (hashed, username))
            conn.commit()
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"DB error: {e}")
        return False
    
# USER MODULE

@app.route("/user")
def user_home():
    if session.get("user"):
        return redirect("/user/dashboard")
    return redirect("/user/login")

@app.route("/user/login", methods=["GET"])
def user_login():
    return render_template("user_login.html")

@app.route("/user/login", methods=["POST"])
def user_login_post():
    username = request.form.get("username")
    password = request.form.get("password")
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    
    conn = sqlite3.connect("traffic.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username=? AND password=? AND role='user'", 
                   (username, hashed_password))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        session["user"] = True
        session["user_username"] = username
        return redirect("/user/dashboard")
    else:
        error_message = "❌ Invalid credentials. Please try again."
        return render_template("user_login.html", error=error_message)

@app.route("/user/register", methods=["GET"])
def user_register():
    return render_template("user_register.html")

@app.route("/user/register", methods=["POST"])
def user_register_post():
    username = request.form.get("username")
    password = request.form.get("password")
    email = request.form.get("email")
    
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    
    conn = sqlite3.connect("traffic.db")
    cursor = conn.cursor()
    
    try:
        cursor.execute("INSERT INTO users (username, password, email, role) VALUES (?, ?, ?, ?)",
                       (username, hashed_password, email, "user"))
        conn.commit()
        success_message = "✅ Registration successful! Please login with your credentials."
        return render_template("user_login.html", success=success_message)
    except sqlite3.IntegrityError:
        error_message = "❌ Username or email already exists. Please try another."
        return render_template("user_register.html", error=error_message)
    finally:
        conn.close()

@app.route("/user/dashboard", methods=["GET"])
def user_dashboard():
    if not session.get("user"):
        return redirect("/user/login")
    
    conn = sqlite3.connect("traffic.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM traffic ORDER BY id DESC LIMIT 1")
    latest_data = cursor.fetchone()
    
    cursor.execute("SELECT location FROM traffic WHERE congestion_level='High' OR congestion_level='Very High' ORDER BY id DESC LIMIT 3")
    hotspots = cursor.fetchall()
    hotspot_count = len(hotspots)
    hotspot_text = hotspots[0][0] if hotspots else "None reported"
    
    cursor.execute("SELECT AVG(vehicle_count) FROM traffic LIMIT 10")
    avg_vehicles = cursor.fetchone()[0] or 100
    avg_speed = max(15, int(60 - (avg_vehicles / 10)))
    
    cursor.execute("SELECT type, location, description FROM alerts ORDER BY id DESC LIMIT 3")
    alerts_data = cursor.fetchall()
    alerts = []
    for alert in alerts_data:
        if alert[0] == "accident":
            alerts.append(f"⚠ Accident in {alert[1]}: {alert[2]}")
        elif alert[0] == "road_work":
            alerts.append(f"🚧 Road work in {alert[1]}: {alert[2]}")
        elif alert[0] == "weather":
            alerts.append(f"🌧 Weather alert for {alert[1]}: {alert[2]}")
    
    if len(alerts) < 3 and latest_data:
        new_alert = generate_and_store_alert(latest_data[1])
        if new_alert["type"] == "accident":
            alerts.append(f"⚠ Accident in {new_alert['location']}: {new_alert['description']}")
        elif new_alert["type"] == "road_work":
            alerts.append(f"🚧 Road work in {new_alert['location']}: {new_alert['description']}")
        elif new_alert["type"] == "weather":
            alerts.append(f"🌧 Weather alert for {new_alert['location']}: {new_alert['description']}")
    
    conn.close()
    
    traffic_data = None
    current_traffic = "Moderate"
    traffic_subtitle = "Area experiencing delays"
    
    if latest_data:
        current_traffic = latest_data[3]
        traffic_subtitle = f"{latest_data[1]} area with {latest_data[2]} vehicles"
        traffic_data = {
            "location": latest_data[1],
            "vehicle_count": latest_data[2],
            "congestion_level": latest_data[3],
            "pedestrian_count": latest_data[4],
            "timestamp": latest_data[5],
            "map_url": f"https://www.google.com/maps/search/{latest_data[1]}"
        }
    
    dashboard_data = {
        "current_traffic": current_traffic,
        "traffic_subtitle": traffic_subtitle,
        "avg_speed": avg_speed,
        "yesterday_text": "Simulated comparison",
        "hotspot_count": hotspot_count,
        "hotspot_text": hotspot_text,
        "peak_hour": "5:30 PM",
        "alerts": alerts
    }
    
    return render_template("user_dashboard.html", 
                          username=session.get("user_username", "User"),
                          traffic_data=traffic_data,
                          dashboard_data=dashboard_data)

@app.route("/user/dashboard_data", methods=["GET"])
def dashboard_data():
    if not session.get("user"):
        return jsonify({"error": "Not logged in"}), 401
    
    fake_data = get_fake_map_data()
    store_traffic_data(fake_data["location"], fake_data["vehicle_count"], 
                       fake_data["congestion_level"], fake_data["pedestrian_count"])
    
    if random.random() < 0.3:
        generate_and_store_alert(fake_data["location"])
    
    conn = sqlite3.connect("traffic.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM traffic ORDER BY id DESC LIMIT 1")
    latest_data = cursor.fetchone()
    
    cursor.execute("SELECT location FROM traffic WHERE congestion_level='High' OR congestion_level='Very High' ORDER BY id DESC LIMIT 3")
    hotspots = cursor.fetchall()
    hotspot_count = len(hotspots)
    hotspot_text = hotspots[0][0] if hotspots else "None reported"
    
    cursor.execute("SELECT AVG(vehicle_count) FROM traffic LIMIT 10")
    avg_vehicles = cursor.fetchone()[0] or 100
    avg_speed = max(15, int(60 - (avg_vehicles / 10)))
    
    cursor.execute("SELECT type, location, description FROM alerts ORDER BY id DESC LIMIT 3")
    alerts_data = cursor.fetchall()
    alerts = []
    for alert in alerts_data:
        if alert[0] == "accident":
            alerts.append(f"⚠ Accident in {alert[1]}: {alert[2]}")
        elif alert[0] == "road_work":
            alerts.append(f"🚧 {alert[2]}")
        elif alert[0] == "weather":
            alerts.append(f"🌧 {alert[2]}")
    
    if len(alerts) < 3 and latest_data:
        new_alert = generate_and_store_alert(latest_data[1])
        if new_alert["type"] == "accident":
            alerts.append(f"⚠ Accident in {new_alert['location']}: {new_alert['description']}")
        elif new_alert["type"] == "road_work":
            alerts.append(f"🚧 {new_alert['description']}")
        elif new_alert["type"] == "weather":
            alerts.append(f"🌧 {new_alert['description']}")
    
    conn.close()
    
    current_traffic = "Moderate"
    traffic_subtitle = "Area experiencing delays"
    recommendation = f"Based on recent data and AI prediction, we recommend avoiding {fake_data['location']} between 4:30 PM and 6:00 PM today."
    
    if latest_data:
        current_traffic = latest_data[3]
        traffic_subtitle = f"{latest_data[1]} area with {latest_data[2]} vehicles"
        recommendation = f"Based on recent data and AI prediction, we recommend avoiding {latest_data[1]} between 4:30 PM and 6:00 PM today."
    
    yesterday_diff = random.randint(-15, 15)
    yesterday_text = f"{abs(yesterday_diff)}% {'faster' if yesterday_diff > 0 else 'slower'} than yesterday"
    
    peak_hour = random.choice(["5:30 PM", "6:00 PM", "5:45 PM"])
    
    now = datetime.datetime.now()
    congestion_level = fake_data["congestion_level"] if not latest_data else latest_data[3]
    if congestion_level in ["High", "Very High"]:
        start_time = (now + datetime.timedelta(hours=1)).strftime("%I:%M %p").lstrip("0")
        end_time = (now + datetime.timedelta(hours=3)).strftime("%I:%M %p").lstrip("0")
    else:
        start_time = (now + datetime.timedelta(hours=2)).strftime("%I:%M %p").lstrip("0")
        end_time = (now + datetime.timedelta(hours=4)).strftime("%I:%M %p").lstrip("0")
    
    location = fake_data["location"] if not latest_data else latest_data[1]
    time_range = f"{start_time} and {end_time}"
    
    return jsonify({
        "current_traffic": current_traffic,
        "traffic_subtitle": traffic_subtitle,
        "avg_speed": avg_speed,
        "yesterday_text": yesterday_text,
        "hotspot_count": hotspot_count,
        "hotspot_text": hotspot_text,
        "peak_hour": peak_hour,
        "alerts": alerts,
        "recommendation": recommendation,
        "recommendation_start_time": start_time,
        "recommendation_end_time": end_time,
        "location": location,
        "time_range": time_range
    })

@app.route("/user/refresh_traffic", methods=["GET"])
def user_refresh_traffic():
    if not session.get("user"):
        return jsonify({"error": "Not logged in"}), 401
    
    fake_data = get_fake_map_data()
    store_traffic_data(fake_data["location"], fake_data["vehicle_count"], 
                       fake_data["congestion_level"], fake_data["pedestrian_count"])
    
    if random.random() < 0.5:
        generate_and_store_alert(fake_data["location"])
    
    fake_data["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fake_data["current_traffic"] = fake_data["congestion_level"]
    fake_data["traffic_subtitle"] = f"{fake_data['location']} area with {fake_data['vehicle_count']} vehicles"
    fake_data["avg_speed"] = max(15, 60 - (fake_data["vehicle_count"] // 10))
    
    yesterday_diff = random.randint(-15, 15)
    fake_data["yesterday_text"] = f"{abs(yesterday_diff)}% {'faster' if yesterday_diff > 0 else 'slower'} than yesterday"
    
    fake_data["hotspot_count"] = random.randint(1, 5)
    fake_data["hotspot_text"] = f"{fake_data['location']} (Heavy Traffic)"
    
    hour = random.randint(1, 12)
    minute = random.randint(0, 59)
    period = random.choice(["AM", "PM"])
    fake_data["peak_hour"] = f"{hour}:{minute:02d} {period}"
    
    conn = sqlite3.connect("traffic.db")
    cursor = conn.cursor()
    cursor.execute("SELECT type, location, description FROM alerts ORDER BY id DESC LIMIT 3")
    alerts_data = cursor.fetchall()
    alerts = []
    for alert in alerts_data:
        if alert[0] == "accident":
            alerts.append(f"⚠ Accident in {alert[1]}: {alert[2]}")
        elif alert[0] == "road_work":
            alerts.append(f"🚧 Road work in {alert[1]}: {alert[2]}")
        elif alert[0] == "weather":
            alerts.append(f"🌧 Weather alert for {alert[1]}: {alert[2]}")
    
    while len(alerts) < 3:
        new_alert = generate_and_store_alert(fake_data["location"])
        if new_alert["type"] == "accident":
            alerts.append(f"⚠ Accident in {new_alert['location']}: {new_alert['description']}")
        elif new_alert["type"] == "road_work":
            alerts.append(f"🚧 Road work in {new_alert['location']}: {new_alert['description']}")
        elif new_alert["type"] == "weather":
            alerts.append(f"🌧 Weather alert for {new_alert['location']}: {new_alert['description']}")
    
    conn.close()
    
    fake_data["alerts"] = alerts[:3]
    
    now = datetime.datetime.now()
    if fake_data["congestion_level"] in ["High", "Very High"]:
        start_time = (now + datetime.timedelta(hours=1)).strftime("%I:%M %p").lstrip("0")
        end_time = (now + datetime.timedelta(hours=3)).strftime("%I:%M %p").lstrip("0")
    else:
        start_time = (now + datetime.timedelta(hours=2)).strftime("%I:%M %p").lstrip("0")
        end_time = (now + datetime.timedelta(hours=4)).strftime("%I:%M %p").lstrip("0")
    fake_data["recommendation"] = f"Based on recent data and AI prediction, we recommend avoiding {fake_data['location']} around {fake_data['peak_hour']}."
    fake_data["recommendation_start_time"] = start_time
    fake_data["recommendation_end_time"] = end_time
    
    fake_data["map_url"] = f"https://www.google.com/maps/search/{fake_data['location']}"
    
    return jsonify(fake_data)

@app.route("/user/logout")
def user_logout():
    session.pop("user", None)
    session.pop("user_username", None)
    return redirect("/user/login")

@app.route("/user/forgot-password", methods=["GET", "POST"])
def user_forgot_password():
    step = request.form.get("step") if request.method == "POST" else "email"
    
    if request.method == "POST":
        if step == "email_submit":
            email = request.form.get("email")
            
            conn = sqlite3.connect("traffic.db")
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM users WHERE email=?", (email,))
            user = cursor.fetchone()
            conn.close()
            
            if not user:
                flash("❌ Email not found in our records.")
                return render_template("user_forgot_password.html", step="email")
            
            username = user[0]
            otp = str(random.randint(100000, 999999))
            session['otp'] = otp
            session['email'] = email
            session['username'] = username
            session['otp_timestamp'] = datetime.datetime.now().timestamp()
            
            try:
                send_otp_email(email, otp)
                flash("✅ OTP sent to your email. Please check your inbox (valid for 10 minutes).", "success")
                return render_template("user_forgot_password.html", step="verify")
            except Exception as e:
                flash(f"❌ Failed to send OTP: {str(e)}")
                return render_template("user_forgot_password.html", step="email")
        
        elif step == "verify_otp":
            entered_otp = request.form.get("otp")
            if (datetime.datetime.now().timestamp() - session.get('otp_timestamp', 0)) > 600:
                flash("❌ OTP has expired. Please request a new one.")
                session.pop("otp", None)
                session.pop("otp_timestamp", None)
                session.pop("username", None)
                session.pop("email", None)
                return render_template("user_forgot_password.html", step="email")
            
            if entered_otp == session.get("otp"):
                temp_password = generate_temp_password()  # Updated function used here
                email = session.get("email")
                username = session.get("username")
                
                if update_temp_password(username, temp_password):
                    try:
                        send_temp_password_email(email, temp_password)
                        session['temp_password'] = hashlib.sha256(temp_password.encode()).hexdigest()  # Store hashed version
                        session['temp_password_raw'] = temp_password  # Store raw version for email display
                        session['temp_password_timestamp'] = datetime.datetime.now().timestamp()
                        flash("✅ Temporary password sent to your email. Please use it within 10 minutes to reset your password.", "success")
                        return redirect("/user/reset-password")
                    except Exception as e:
                        flash(f"❌ Failed to send temporary password: {str(e)}")
                        return render_template("user_forgot_password.html", step="verify")
                else:
                    flash("❌ Failed to update temporary password in database.")
                    return render_template("user_forgot_password.html", step="verify")
            else:
                flash("❌ Invalid OTP. Please try again.")
                return render_template("user_forgot_password.html", step="verify")
    
    return render_template("user_forgot_password.html", step=step)

@app.route("/user/reset-password", methods=["GET", "POST"])
def user_reset_password():
    if request.method == "GET":
        if "temp_password" not in session or "email" not in session or "username" not in session or "temp_password_timestamp" not in session:
            flash("❌ Session expired or invalid. Please start the password reset process again.")
            return redirect("/user/forgot-password")
        return render_template("user_reset_password.html")
    
    if request.method == "POST":
        temp_password_input = request.form.get("temp_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")
        email = session.get("email")
        username = session.get("username")
        
        if (datetime.datetime.now().timestamp() - session.get('temp_password_timestamp', 0)) > 600:
            flash("❌ Temporary password has expired. Please request a new one.")
            session.pop("temp_password", None)
            session.pop("temp_password_raw", None)
            session.pop("temp_password_timestamp", None)
            session.pop("username", None)
            session.pop("email", None)
            return redirect("/user/forgot-password")
        
        # Compare hashed input with stored hashed temp password
        hashed_temp_input = hashlib.sha256(temp_password_input.encode()).hexdigest()
        stored_hashed_temp = session.get("temp_password")
        
        if hashed_temp_input != stored_hashed_temp:
            flash("❌ Invalid temporary password. Please check and try again.")
            return render_template("user_reset_password.html")
        
        if new_password != confirm_password:
            flash("❌ New passwords do not match. Please try again.")
            return render_template("user_reset_password.html")
        
        hashed_new_password = hashlib.sha256(new_password.encode()).hexdigest()
        conn = sqlite3.connect("traffic.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password=? WHERE username=? AND email=?", 
                       (hashed_new_password, username, email))
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        
        if affected_rows == 0:
            flash("❌ Failed to update password. User not found or data mismatch.")
            return render_template("user_reset_password.html")
        
        session.pop("otp", None)
        session.pop("email", None)
        session.pop("otp_timestamp", None)
        session.pop("temp_password", None)
        session.pop("temp_password_raw", None)
        session.pop("username", None)
        session.pop("temp_password_timestamp", None)
        
        flash("✅ Password successfully reset! Please log in with your new password.", "success")
        return redirect("/user/login")
    
@app.route("/user/verify_otp", methods=["GET", "POST"])
def verify_otp():
    if request.method == "GET":
        if "otp" not in session or "email" not in session:
            return redirect("/user/forgot-password")
        return render_template("user_verify_otp.html")
    
    email = session.get("email")
    input_otp = request.form.get("otp")
    
    if (datetime.datetime.now().timestamp() - session.get('otp_timestamp', 0)) > 600:
        flash("❌ OTP has expired. Please request a new one.")
        session.pop("otp", None)
        session.pop("otp_timestamp", None)
        return redirect("/user/forgot-password")
    
    if input_otp == session.get("otp") and email:
        conn = sqlite3.connect("traffic.db")
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users WHERE email=?", (email,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            username = result[0]
            temp_password = generate_temp_password()  # Updated function used here
            if update_temp_password(username, temp_password):
                try:
                    send_temp_password_email(email, temp_password)
                    session['temp_password'] = hashlib.sha256(temp_password.encode()).hexdigest()  # Store hashed version
                    session['temp_password_raw'] = temp_password  # Store raw version
                    session['username'] = username
                    session['temp_password_timestamp'] = datetime.datetime.now().timestamp()
                    flash("✅ Temporary password sent to your email. Please use it within 10 minutes to reset your password.", "success")
                    return redirect("/user/reset-password")
                except Exception as e:
                    flash(f"❌ Failed to send temporary password: {str(e)}")
                    return render_template("user_verify_otp.html")
            else:
                flash("❌ Failed to update temporary password in database.")
                return render_template("user_verify_otp.html")
        else:
            flash("❌ Email not registered.")
            return render_template("user_forgot_password.html", step="email")
    else:
        flash("❌ Invalid OTP. Please try again.")
        return render_template("user_verify_otp.html")

# NEW ROUTE: Real-time Traffic Updates
@app.route("/user/realtime_traffic", methods=["GET"])
def realtime_traffic():
    if not session.get("user"):
        return jsonify({"error": "Not logged in"}), 401
    
    fake_data = get_fake_map_data()
    store_traffic_data(fake_data["location"], fake_data["vehicle_count"], 
                       fake_data["congestion_level"], fake_data["pedestrian_count"])
    
    if random.random() < 0.4:
        accident_data = get_fake_accident_data(fake_data["location"])
        store_accident_data(accident_data["location"], accident_data["description"], accident_data["severity"])
        generate_and_store_alert(fake_data["location"])
    
    conn = sqlite3.connect("traffic.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM traffic ORDER BY id DESC LIMIT 1")
    latest_traffic = cursor.fetchone()
    cursor.execute("SELECT * FROM accidents ORDER BY id DESC LIMIT 1")
    latest_accident = cursor.fetchone()
    cursor.execute("SELECT type, location, description FROM alerts ORDER BY id DESC LIMIT 1")
    latest_alert = cursor.fetchone()
    conn.close()
    
    response = {
        "traffic": {
            "location": latest_traffic[1] if latest_traffic else fake_data["location"],
            "vehicle_count": latest_traffic[2] if latest_traffic else fake_data["vehicle_count"],
            "congestion_level": latest_traffic[3] if latest_traffic else fake_data["congestion_level"],
            "pedestrian_count": latest_traffic[4] if latest_traffic else fake_data["pedestrian_count"],
            "timestamp": latest_traffic[5] if latest_traffic else datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        },
        "accident": {
            "location": latest_accident[1] if latest_accident else None,
            "description": latest_accident[2] if latest_accident else None,
            "severity": latest_accident[3] if latest_accident else None
        },
        "alert": {
            "type": latest_alert[0] if latest_alert else None,
            "location": latest_alert[1] if latest_alert else None,
            "description": latest_alert[2] if latest_alert else None
        }
    }
    
    return jsonify(response)

# OTHER ROUTES

@app.route('/')
def index():
    return render_template('home.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

def get_fake_map_data():
    cuttack_locations = {
        "Bidanasi": {"vehicle_range": (70, 200), "pedestrian_range": (40, 110), "congestion": ["Moderate", "High"]},
        "CDA Sector-6": {"vehicle_range": (80, 220), "pedestrian_range": (45, 120), "congestion": ["Low", "Moderate"]},
        "CDA Sector-7": {"vehicle_range": (75, 210), "pedestrian_range": (40, 115), "congestion": ["Low", "Moderate"]},
        "CDA Sector-9": {"vehicle_range": (85, 230), "pedestrian_range": (50, 125), "congestion": ["Low", "Moderate"]},
        "Tulsipur": {"vehicle_range": (65, 190), "pedestrian_range": (35, 100), "congestion": ["Moderate", "High"]},
        "Buxi Bazaar": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["High", "Very High"]},
        "Chandni Chowk": {"vehicle_range": (55, 170), "pedestrian_range": (25, 85), "congestion": ["High", "Very High"]},
        "Mahima Nagar": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Ranihat": {"vehicle_range": (70, 200), "pedestrian_range": (35, 95), "congestion": ["Moderate", "High"]},
        "Badambadi": {"vehicle_range": (90, 250), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Link Road": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Sutahat": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["High", "Very High"]},
        "Jobra": {"vehicle_range": (80, 220), "pedestrian_range": (40, 110), "congestion": ["Moderate", "High"]},
        "Mangalabag": {"vehicle_range": (75, 200), "pedestrian_range": (40, 100), "congestion": ["Moderate", "High"]},
        "Dolamundai": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["High", "Very High"]},
        "Khan Nagar": {"vehicle_range": (70, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Professor Para": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["Low", "Moderate"]},
        "Gandarpur": {"vehicle_range": (85, 230), "pedestrian_range": (50, 120), "congestion": ["Moderate", "High"]},
        "Nayabazar": {"vehicle_range": (70, 200), "pedestrian_range": (35, 100), "congestion": ["High", "Very High"]},
        "Chauliaganj": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Moderate", "High"]},
        "Kathajodi Road": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Telenga Bazar": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["High", "Very High"]},
        "Mal Godown": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Moderate", "High"]},
        "Barabati": {"vehicle_range": (90, 240), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Cantonment Road": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Low", "Moderate"]},
        "Puri Ghat": {"vehicle_range": (55, 170), "pedestrian_range": (25, 85), "congestion": ["Moderate", "High"]},
        "Dargha Bazar": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["High", "Very High"]},
        "Jagatpur": {"vehicle_range": (100, 280), "pedestrian_range": (55, 140), "congestion": ["Low", "Moderate"]},
        "Nimpur": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Low", "Moderate"]},
        "Phulnakhara": {"vehicle_range": (90, 250), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Trisulia": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Low", "Moderate"]},
        "Niali Road": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Choudwar": {"vehicle_range": (95, 260), "pedestrian_range": (50, 135), "congestion": ["Moderate", "High"]},
        "Athagarh": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Low", "Moderate"]},
        "Narasinghpur": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Kakhadi": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Salepur": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Kendrapara Road": {"vehicle_range": (90, 240), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Mahanga": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Pattamundai": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Moderate", "High"]},
        "Banki": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Madhupatna": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Kalyan Nagar": {"vehicle_range": (70, 200), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Nuapatna": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Sikharpur": {"vehicle_range": (75, 210), "pedestrian_range": (40, 110), "congestion": ["Moderate", "High"]},
        "Gopalpur": {"vehicle_range": (80, 220), "pedestrian_range": (45, 115), "congestion": ["Low", "Moderate"]},
        "Balikuda": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Kandarpur": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Tangi": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["Low", "Moderate"]},
        "Nischintakoili": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Moderate", "High"]},
        "Balisahi": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Raghunathpur": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Kuanpal": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Nemalo": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Low", "Moderate"]},
        "Charbatia": {"vehicle_range": (90, 250), "pedestrian_range": (50, 130), "congestion": ["Moderate", "High"]},
        "Kapaleswar": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Biribati": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Sankhatras": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Devi Ghat": {"vehicle_range": (60, 180), "pedestrian_range": (30, 90), "congestion": ["Moderate", "High"]},
        "Harirajpur": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Gadgadia Ghat": {"vehicle_range": (55, 170), "pedestrian_range": (25, 85), "congestion": ["Moderate", "High"]},
        "Chhatia": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Low", "Moderate"]},
        "Bhadimula": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Khandeita": {"vehicle_range": (85, 230), "pedestrian_range": (45, 120), "congestion": ["Moderate", "High"]},
        "Sungra": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]},
        "Chhagaon": {"vehicle_range": (65, 190), "pedestrian_range": (35, 95), "congestion": ["Low", "Moderate"]},
        "Khandol": {"vehicle_range": (70, 200), "pedestrian_range": (40, 100), "congestion": ["Low", "Moderate"]},
        "Raisunguda": {"vehicle_range": (80, 220), "pedestrian_range": (45, 110), "congestion": ["Moderate", "High"]},
        "Manijanga": {"vehicle_range": (75, 210), "pedestrian_range": (40, 105), "congestion": ["Low", "Moderate"]}
    }
    city = random.choice(list(cuttack_locations.keys()))
    city_data = cuttack_locations[city]
    return {
        "location": city,
        "vehicle_count": random.randint(*city_data["vehicle_range"]),
        "pedestrian_count": random.randint(*city_data["pedestrian_range"]),
        "congestion_level": random.choice(city_data["congestion"]),
        "map_url": f"https://www.google.com/maps/search/{city}"
    }

def get_fake_weather_data(location="Unknown"):
    weather_conditions = ["Sunny ☀", "Cloudy ☁", "Rainy 🌧", "Stormy ⛈", "Foggy 🌫", "Windy 💨"]
    temperature = random.randint(10, 40)
    humidity = random.randint(40, 90)
    return {
        "location": location.capitalize(),
        "weather": random.choice(weather_conditions),
        "temperature": f"{temperature}°C",
        "humidity": f"{humidity}%"
    }

def store_traffic_data(location, vehicle_count, congestion_level, pedestrian_count):
    conn = sqlite3.connect("traffic.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO traffic (location, vehicle_count, congestion_level, pedestrian_count) VALUES (?, ?, ?, ?)", 
                   (location, vehicle_count, congestion_level, pedestrian_count))
    conn.commit()
    conn.close()

@app.route('/traffic_data', methods=['GET'])
def traffic_data():
    fake_data = get_fake_map_data()
    store_traffic_data(fake_data["location"], fake_data["vehicle_count"], fake_data["congestion_level"], fake_data["pedestrian_count"])
    return jsonify(fake_data)

@app.route('/weather_data', methods=['GET'])
def weather_data():
    location = request.args.get("location", "Downtown")
    return jsonify(get_fake_weather_data(location))


@app.route('/chatbot', methods=['POST'])
def chatbot():
    user_query = request.json.get("query", "").lower()
    response_text = "Sorry, I couldn't understand your request. Please ask about traffic, weather, accidents, or get directions at a specific location."
    location = None
    audio_response = None

    query_words = user_query.split()
    for i, word in enumerate(query_words):
        if word in ["at", "in", "near"]:
            location = " ".join(query_words[i+1:]).strip()
            break

    # Define cuttack_locations from existing data
    cuttack_locations = {
        "bidanasi": "Bidanasi", "cda sector-6": "CDA Sector-6", "cda sector-7": "CDA Sector-7",
        "cda sector-9": "CDA Sector-9", "tulsipur": "Tulsipur", "buxi bazaar": "Buxi Bazaar",
        "chandni chowk": "Chandni Chowk", "mahima nagar": "Mahima Nagar", "ranihat": "Ranihat",
        "badambadi": "Badambadi", "link road": "Link Road", "sutahat": "Sutahat", "jobra": "Jobra",
        "mangalabag": "Mangalabag", "dolamundai": "Dolamundai", "khan nagar": "Khan Nagar",
        "professor para": "Professor Para", "gandarpur": "Gandarpur", "nayabazar": "Nayabazar",
        "chauliaganj": "Chauliaganj", "kathajodi road": "Kathajodi Road", "telenga bazar": "Telenga Bazar",
        "mal godown": "Mal Godown", "barabati": "Barabati", "cantonment road": "Cantonment Road",
        "puri ghat": "Puri Ghat", "dargha bazar": "Dargha Bazar", "jagatpur": "Jagatpur",
        "nimpur": "Nimpur", "phulnakhara": "Phulnakhara", "trisulia": "Trisulia", "niali road": "Niali Road",
        "choudwar": "Choudwar", "athagarh": "Athagarh", "narasinghpur": "Narasinghpur", "kakhadi": "Kakhadi",
        "salepur": "Salepur", "kendrapara road": "Kendrapara Road", "mahanga": "Mahanga",
        "pattamundai": "Pattamundai", "banki": "Banki", "madhupatna": "Madhupatna",
        "kalyan nagar": "Kalyan Nagar", "nuapatna": "Nuapatna", "sikharpur": "Sikharpur",
        "gopalpur": "Gopalpur", "balikuda": "Balikuda", "kandarpur": "Kandarpur", "tangi": "Tangi",
        "nischintakoili": "Nischintakoili", "balisahi": "Balisahi", "raghunathpur": "Raghunathpur",
        "kuanpal": "Kuanpal", "nemalo": "Nemalo", "charbatia": "Charbatia", "kapaleswar": "Kapaleswar",
        "biribati": "Biribati", "sankhatras": "Sankhatras", "devi ghat": "Devi Ghat",
        "harirajpur": "Harirajpur", "gadgadia ghat": "Gadgadia Ghat", "chhatia": "Chhatia",
        "bhadimula": "Bhadimula", "khandeita": "Khandeita", "sungra": "Sungra", "chhagaon": "Chhagaon",
        "khandol": "Khandol", "raisunguda": "Raisunguda", "manijanga": "Manijanga"
    }

    # Check if location exists in cuttack_locations
    if location and location.lower() in cuttack_locations:
        location = cuttack_locations[location.lower()]  # Convert to proper case
        if "traffic" in user_query:
            fake_data = get_fake_map_data()
            fake_data["location"] = location
            store_traffic_data(fake_data["location"], fake_data["vehicle_count"], 
                               fake_data["congestion_level"], fake_data["pedestrian_count"])
            response_text = f"Traffic at {location}: {fake_data['congestion_level']} with {fake_data['vehicle_count']} vehicles and {fake_data['pedestrian_count']} pedestrians."
        elif "weather" in user_query:
            weather_data = get_fake_weather_data(location)
            response_text = f"Weather at {location}: {weather_data['weather']}, Temperature: {weather_data['temperature']}, Humidity: {weather_data['humidity']}."
        elif "accident" in user_query:
            accident_data = get_fake_accident_data(location)
            store_accident_data(accident_data["location"], accident_data["description"], accident_data["severity"])
            response_text = f"Accident at {location}: {accident_data['description']} (Severity: {accident_data['severity']})."
        elif "directions" in user_query:
            response_text = f"To get directions to {location}, visit: https://www.google.com/maps/search/{location}"

    # Optional: Add audio response using gTTS
    if response_text:
        try:
            tts = gTTS(text=response_text, lang='en')
            # Generate a unique filename using a timestamp
            timestamp = int(time.time())
            audio_filename = f"response_{timestamp}.mp3"
            audio_file = os.path.join("static", audio_filename)
            tts.save(audio_file)
            audio_response = url_for('static', filename=audio_filename)
        except Exception as e:
            logger.error(f"Error generating audio response: {e}")
            audio_response = None

    return jsonify({"response": response_text, "audio": audio_response})

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)