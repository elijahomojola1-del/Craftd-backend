"""Subscription payments through Paystack.

Flow: the app asks us to start a payment, we ask Paystack for a checkout
page and hand its address back, the user pays there, and Paystack tells us
the result twice over: the user's browser returns with a reference that we
verify, and Paystack's server calls our webhook. Either one switches the
subscription on; doing both is harmless because a payment is only ever
applied once.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import AppSettings, Payment, Profile, SubscriptionRequest

PAYSTACK_API = 'https://api.paystack.co'


class PaymentError(Exception):
    """Something the user should be told about."""


def secret_key():
    return getattr(settings, 'PAYSTACK_SECRET_KEY', '') or ''


def payment_available():
    return bool(secret_key()) and AppSettings.load().subscription_price_naira > 0


def price_text(config=None):
    config = config or AppSettings.load()
    if config.subscription_price_text:
        return config.subscription_price_text
    if config.subscription_price_naira > 0:
        return f'₦{config.subscription_price_naira:,} for {config.subscription_days} days'
    return ''


def _paystack(method, path, **kwargs):
    try:
        response = requests.request(
            method,
            f'{PAYSTACK_API}{path}',
            headers={'Authorization': f'Bearer {secret_key()}'},
            timeout=20,
            **kwargs,
        )
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaymentError('Could not reach the payment service. Please try again.') from exc

    if not body.get('status'):
        raise PaymentError(body.get('message') or 'The payment service refused the request.')
    return body['data']


def start_payment(user):
    """Create a pending payment and return Paystack's checkout address."""
    if not payment_available():
        raise PaymentError('Online payment is not available yet.')
    if not user.email:
        raise PaymentError('Your account has no email address to send a receipt to.')

    config = AppSettings.load()
    payment = Payment.objects.create(
        user=user,
        reference=f'craftd-{user.id}-{secrets.token_hex(8)}',
        amount_kobo=config.subscription_price_naira * 100,
        days=config.subscription_days,
    )

    callback = getattr(settings, 'FRONTEND_URL', '').rstrip('/')
    data = _paystack('POST', '/transaction/initialize', json={
        'email': user.email,
        'amount': payment.amount_kobo,
        'currency': 'NGN',
        'reference': payment.reference,
        'callback_url': f'{callback}/subscribe' if callback else None,
        'metadata': {'user_id': user.id, 'purpose': 'subscription'},
    })
    return {'authorization_url': data['authorization_url'], 'reference': payment.reference}


def apply_payment(reference, paid_amount_kobo, currency='NGN'):
    """Switch the subscription on for a payment Paystack says succeeded.
    Safe to call more than once for the same reference."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(reference=reference).first()
        if not payment:
            return None
        if payment.status == 'success':
            return payment
        # Never trust a success for less than (or a different currency from)
        # what was asked for.
        if currency != 'NGN' or int(paid_amount_kobo) < payment.amount_kobo:
            payment.status = 'failed'
            payment.save(update_fields=['status'])
            return payment

        now = timezone.now()
        profile, _ = Profile.objects.select_for_update().get_or_create(user=payment.user)
        still_running = profile.is_subscribed and profile.subscription_expires and profile.subscription_expires > now
        start = profile.subscription_expires if still_running else now
        profile.is_subscribed = True
        profile.subscription_expires = start + timedelta(days=payment.days)
        profile.save(update_fields=['is_subscribed', 'subscription_expires'])

        payment.status = 'success'
        payment.paid_at = now
        payment.save(update_fields=['status', 'paid_at'])
        SubscriptionRequest.objects.filter(user=payment.user, handled=False).update(handled=True)
        return payment


def verify_payment(user, reference):
    """Ask Paystack what happened to one of this user's payments."""
    payment = Payment.objects.filter(reference=reference, user=user).first()
    if not payment:
        raise PaymentError('We could not find that payment.')
    if payment.status == 'success':
        return payment

    data = _paystack('GET', f'/transaction/verify/{reference}')
    if data.get('status') == 'success':
        return apply_payment(reference, data.get('amount', 0), data.get('currency', 'NGN'))
    if data.get('status') in ('failed', 'abandoned', 'reversed'):
        payment.status = 'failed'
        payment.save(update_fields=['status'])
    return payment


def valid_signature(raw_body, signature):
    """Paystack signs each webhook with our secret key (HMAC SHA-512)."""
    key = secret_key()
    if not key or not signature:
        return False
    expected = hmac.new(key.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
