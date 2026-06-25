import smtplib
from email.message import EmailMessage
import ssl

msg = EmailMessage()
msg.set_content("Test email from Python backend")
msg['Subject'] = "Test Teleophtalmo"
msg['From'] = "support@teleophta.fr"
msg['To'] = "test@example.com"

context = ssl._create_unverified_context()

try:
    with smtplib.SMTP('193.95.84.21', 587, timeout=10) as s:
        s.set_debuglevel(1)
        s.starttls(context=context)
        s.send_message(msg)
    print("Success!")
except Exception as e:
    print("Error:", str(e))
