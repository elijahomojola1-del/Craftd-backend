import requests
import os


def send_push_notification(push_token, title, body, data=None):
    if not push_token:
        return None

    message = {
        'to': push_token,
        'sound': 'default',
        'title': title,
        'body': body,
        'data': data or {},
    }

    try:
        response = requests.post(
            'https://exp.host/--/api/v2/push/send',
            json=message,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            },
            timeout=5,
        )
        return response.json()
    except requests.RequestException as e:
        print(f"Push notification failed: {e}")
        return None


def send_sms(phone_number, message):
    if not phone_number:
        return None

    api_key = os.environ.get('TERMII_API_KEY')
    if not api_key:
        print("SMS failed: TERMII_API_KEY not set")
        return None

    payload = {
        'to': phone_number,
        'from': 'CRAFTD',
        'sms': message,
        'type': 'plain',
        'channel': 'generic',
        'api_key': api_key,
    }

    try:
        response = requests.post(
            'https://api.ng.termii.com/api/sms/send',
            json=payload,
            timeout=5,
        )
        return response.json()
    except requests.RequestException as e:
        print(f"SMS failed: {e}")
        return None