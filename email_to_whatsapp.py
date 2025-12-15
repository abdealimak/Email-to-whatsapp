import imaplib
import email
from email.header import decode_header
import time
import os
import sys
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from dotenv import load_dotenv

load_dotenv()

EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

TW_SID = os.getenv("TWILIO_ACCOUNT_SID")
TW_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TW_FROM = os.getenv("TWILIO_WHATSAPP_FROM")
TO_WHATSAPP = os.getenv("TO_WHATSAPP")

if not all([EMAIL_HOST, EMAIL_USER, EMAIL_PASS, TW_SID, TW_TOKEN, TW_FROM, TO_WHATSAPP]):
    print("Missing required environment variables. Please check your .env file.")
    sys.exit(1)

client = Client(TW_SID, TW_TOKEN)

def connect_imap():
    imap = imaplib.IMAP4_SSL(EMAIL_HOST)
    imap.login(EMAIL_USER, EMAIL_PASS)
    return imap

def decode_mime(s):
    if not s:
        return ""
    parts = decode_header(s)
    decoded = ''
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded += part.decode(enc or 'utf-8', errors='ignore')
        else:
            decoded += part
    return decoded

def get_body(msg):
    if msg.is_multipart():

        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ct == "text/plain" and "attachment" not in disp:
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="ignore")

        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="ignore")
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, errors="ignore")
    return ""

def fetch_unseen(imap):
    imap.select("INBOX")
    status, messages = imap.search(None, '(UNSEEN)')
    if status != "OK":
        return []
    email_ids = messages[0].split()
    results = []
    for eid in email_ids:
        res, data = imap.fetch(eid, "(RFC822)")
        if res != "OK" or not data or data[0] is None:
            continue
        try:
            msg = email.message_from_bytes(data[0][1])
        except Exception:
            continue
        subject = decode_mime(msg.get("Subject", ""))
        from_ = decode_mime(msg.get("From", ""))

        date = decode_mime(msg.get("Date", ""))
        body = get_body(msg) or ""
        preview = (body.strip().replace("\r", " ").replace("\n", " "))[:400]
        results.append({
            "id": eid,
            "subject": subject,
            "from": from_,
            "date": date,
            "body": body,
            "preview": preview
        })
    return results

def mark_seen(imap, eid):
    imap.store(eid, '+FLAGS', '\\Seen')

def send_whatsapp(text):
    try:
        msg = client.messages.create(from_=TW_FROM, to=TO_WHATSAPP, body=text)
        return msg.sid
    except TwilioRestException as e:

        return f"ERROR: {e.msg} (code {getattr(e, 'code', 'N/A')})"

def send_batch(imap, emails):
    if not emails:
        print("No emails selected to send.")
        return

    for i, e in enumerate(emails, start=1):
        header = f"📧 From: {e['from']}\n💬 Subject: {e['subject']}\nDate: {e['date']}\n\n"
        body_text = e['body'][:1000]
        text = header + body_text
        print(f"\nSending {i}/{len(emails)} -> Subject: {e['subject'][:60]}")
        result = send_whatsapp(text)
        print("Result:", result)

        if isinstance(result, str) and not result.startswith("ERROR"):
            try:
                mark_seen(imap, e["id"])
            except Exception as ex:
                print("Warning: couldn't mark email seen:", ex)
        else:
            print("Message not marked seen due to send error.")

def interactive_loop():
    imap = connect_imap()
    try:
        while True:
            print("\nFetching unread emails...")
            emails = fetch_unseen(imap)
            n = len(emails)
            print(f"Found {n} unread email(s).")
            if n > 0:

                for idx, e in enumerate(emails[-10:], start=max(1, n - 9)):
                    print(f"[{idx}] From: {e['from']}, Subject: {e['subject'][:60]}")
                    print(f"     Preview: {e['preview'][:120]}")
                print("\nOptions:")
                print(" 1 - Send LAST 1 unread email")
                print(" 2 - Send LAST 3 unread emails")
                print(" 3 - Send ALL unread emails")
            else:
                print("No unread emails right now.")
            print(" r - Refresh")
            print(" q - Quit")
            choice = input("\nEnter option (1/2/3/r/q): ").strip().lower()
            if choice == 'q':
                print("Quitting.")
                break
            if choice == 'r':
                continue
            if n == 0:
                print("No unread messages to send. Refresh or Quit.")
                continue

            if choice == '1':
                selected = emails[-1:] if n >= 1 else []
            elif choice == '2':
                selected = emails[-3:] if n >= 1 else []
            elif choice == '3':
                selected = emails[:]
            else:
                print("Invalid option. Try again.")
                continue

            print(f"\nYou selected {len(selected)} email(s) to send.")
            for i, e in enumerate(selected, start=1):
                print(f" {i}. Subject: {e['subject'][:80]} | From: {e['from']}")
            confirm = input("Send these to WhatsApp? (y/n): ").strip().lower()
            if confirm == 'y':
                send_batch(imap, selected)
            else:
                print("Cancelled. No messages were sent.")

            cont = input("\nDo you want to continue? (y to continue, any other key to quit): ").strip().lower()
            if cont != 'y':
                print("Exiting interactive session.")
                break
    finally:
        try:
            imap.logout()
        except Exception:
            pass

if __name__ == "__main__":
    interactive_loop()
