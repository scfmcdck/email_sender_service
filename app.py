from flask import Flask, render_template, request, redirect, url_for, session
import smtplib
from email.message import EmailMessage
import csv
import json
import io
import re
from datetime import datetime
import pytz  # ✅ добавлено для московского времени

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'

EMAIL_REGEX = re.compile(r"[^@]+@[^@]+\.[^@]+")

def is_valid_email(email):
    return EMAIL_REGEX.match(email)

def extract_emails_from_file(uploaded_file):
    if not uploaded_file:
        return [], {}

    filename = uploaded_file.filename
    data = uploaded_file.read()

    raw_emails = []
    valid_emails = set()

    try:
        if filename.endswith('.csv'):
            text = data.decode('utf-8')
            reader = csv.reader(io.StringIO(text))
            for row in reader:
                for cell in row:
                    raw_emails.append(cell.strip())

        elif filename.endswith('.json'):
            text = data.decode('utf-8')
            content = json.loads(text)
            if isinstance(content, list):
                raw_emails.extend(email.strip() for email in content)
            elif isinstance(content, dict):
                raw_emails.extend(email.strip() for email in content.values())

        for email in raw_emails:
            if is_valid_email(email):
                valid_emails.add(email)

        stats = {
            "file_total": len(raw_emails),
            "valid": len(valid_emails),
            "duplicates_removed": len(raw_emails) - len(valid_emails)
        }

        return list(valid_emails), stats

    except Exception as e:
        print(f"Ошибка при чтении файла: {e}")
        return [], {"error": str(e)}

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            smtp_server = request.form['smtp_server']
            smtp_port = int(request.form['smtp_port'])
            smtp_username = request.form['smtp_username']
            sender_email = request.form['sender_email']
            password = request.form['password']
            subject = request.form['subject']
            message_body = request.form['message']

            form_recipients = request.form['recipients']
            manual_emails = [email.strip() for email in form_recipients.split(',') if is_valid_email(email)]

            file = request.files.get('file')
            file_emails, file_stats = extract_emails_from_file(file)

            all_recipients = list(set(manual_emails + file_emails))

            if not all_recipients:
                raise ValueError("Не указано ни одного валидного email-адреса.")

            msg = EmailMessage()
            msg['From'] = sender_email
            msg['Subject'] = subject
            msg.set_content(message_body)

            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_username, password)
                for recipient in all_recipients:
                    msg['To'] = recipient
                    server.send_message(msg)
                    del msg['To']

            # Получаем текущее время в часовом поясе Москвы
            moscow_time = datetime.now(pytz.timezone("Europe/Moscow")).strftime("%d.%m.%Y %H:%M:%S")

            session['form_data'] = request.form.to_dict()
            session['summary'] = {
                "manual_total": len(manual_emails),
                "file_total": file_stats.get("file_total", 0),
                "valid_from_file": file_stats.get("valid", 0),
                "duplicates_removed": file_stats.get("duplicates_removed", 0),
                "final_total": len(all_recipients),
                "timestamp": moscow_time  # ✅ московское время
            }

            return redirect(url_for("index", sent="1"))

        except Exception as e:
            return render_template("index.html", error=str(e), form=request.form)

    success = request.args.get("sent") == "1"
    form_data = session.get('form_data', {})
    summary = session.get('summary') if success else None

    return render_template("index.html", form=form_data, success=success, summary=summary)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)