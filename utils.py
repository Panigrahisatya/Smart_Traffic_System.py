import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path="main.env")

def send_otp_email(to_email, otp):
    from_email = os.getenv("ADMIN_EMAIL_ADDRESS")
    from_password = os.getenv("ADMIN_EMAIL_PASSWORD")
    subject = "🔐 Admin OTP Verification - Traffic Monitoring System"

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2>Admin Password Reset Request</h2>
        <p>Hello Admin,</p>
        <p>You requested to reset your password. Use the following One-Time Password (OTP) to continue:</p>
        <div style="font-size: 22px; font-weight: bold; color: #333; background: #f0f0f0; padding: 10px; border-radius: 6px; display: inline-block;">
            {otp}
        </div>
        <p style="margin-top: 20px;">This OTP is valid for 10 minutes.</p>
        <p>If you did not request this, please ignore this email.</p>
        <br>
        <p>🚦 Traffic Monitoring Admin Panel</p>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(from_email, from_password)
        server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
        print("✅ OTP email sent successfully")
    except Exception as e:
        print("❌ Failed to send OTP email:", str(e))
