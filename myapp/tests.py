import re

from django.contrib.auth.models import User
from django.core import mail
from rest_framework.test import APITestCase

from .models import Block, Booking, Gig, PasswordResetCode, Profile, Report

PASSWORD = 'Str0ng-pass-word'


def make_user(email, name='', role='provider'):
    user = User.objects.create_user(username=email, email=email, password=PASSWORD)
    Profile.objects.create(user=user, display_name=name, role=role)
    return user


def reset_code_from_email():
    return re.search(r'\b(\d{6})\b', mail.outbox[-1].body).group(1)


class RegistrationTests(APITestCase):
    def test_register_saves_name_and_role(self):
        res = self.client.post('/app/register/', {
            'username': 'Ada@Example.com', 'email': 'Ada@Example.com',
            'password': PASSWORD, 'display_name': 'Ada', 'role': 'client',
        })
        self.assertEqual(res.status_code, 201, res.data)
        profile = Profile.objects.get(user__username='ada@example.com')
        self.assertEqual((profile.display_name, profile.role), ('Ada', 'client'))

    def test_weak_password_and_duplicate_email_rejected(self):
        make_user('ada@example.com')
        weak = self.client.post('/app/register/', {'username': 'b@example.com', 'email': 'b@example.com', 'password': '12345'})
        self.assertEqual(weak.status_code, 400)
        self.assertIn('password', weak.data)
        dup = self.client.post('/app/register/', {'username': 'x@example.com', 'email': 'ADA@example.com', 'password': PASSWORD})
        self.assertEqual(dup.status_code, 400)


class NamesTests(APITestCase):
    def test_emails_are_not_shown_to_other_users(self):
        named = make_user('named@example.com', name='Tunde the Tailor')
        unnamed = make_user('plain.person@example.com')
        Gig.objects.create(provider=named, title='Suits', description='d', category='design')
        Gig.objects.create(provider=unnamed, title='Shirts', description='d', category='design')

        body = self.client.get('/app/gigs/').content.decode()
        self.assertIn('Tunde the Tailor', body)
        self.assertIn('plain.person', body)
        self.assertNotIn('@example.com', body)


class GigTests(APITestCase):
    def setUp(self):
        self.owner = make_user('owner@example.com', name='Owner')
        self.other = make_user('other@example.com', name='Other')
        self.gig = Gig.objects.create(
            provider=self.owner, title='Plumbing', description='Pipes',
            category='home_repairs', location='Lagos',
        )

    def titles(self, url):
        return [g['title'] for g in self.client.get(url).data]

    def test_only_owner_can_edit_or_delete(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.patch(f'/app/gigs/{self.gig.id}/', {'title': 'Hacked'}).status_code, 403)
        self.assertEqual(self.client.delete(f'/app/gigs/{self.gig.id}/').status_code, 403)

        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.patch(f'/app/gigs/{self.gig.id}/', {'title': 'Plumbing & pipes'}).status_code, 200)
        self.assertEqual(self.client.delete(f'/app/gigs/{self.gig.id}/').status_code, 204)

    def test_search_and_category_filter(self):
        Gig.objects.create(provider=self.other, title='Logo design', description='Brands', category='design', location='Abuja')
        self.assertEqual(self.titles('/app/gigs/?search=pipes'), ['Plumbing'])
        self.assertEqual(self.titles('/app/gigs/?search=abuja'), ['Logo design'])
        self.assertEqual(self.titles('/app/gigs/?category=design'), ['Logo design'])
        self.assertEqual(len(self.titles('/app/gigs/')), 2)

    def test_gig_limit_and_no_price_needed(self):
        self.client.force_authenticate(self.other)
        for n in range(3):
            res = self.client.post('/app/gigs/', {'title': f'Skill {n}', 'description': 'd', 'category': 'design'})
            self.assertEqual(res.status_code, 201, res.data)
        fourth = self.client.post('/app/gigs/', {'title': 'Skill 4', 'description': 'd', 'category': 'design'})
        self.assertEqual(fourth.status_code, 400)

    def test_cannot_book_own_gig(self):
        self.client.force_authenticate(self.owner)
        res = self.client.post('/app/bookings/', {'gig': self.gig.id, 'proposed_date': '2030-01-01T00:00:00'})
        self.assertEqual(res.status_code, 400)


class PasswordTests(APITestCase):
    def setUp(self):
        self.user = make_user('ada@example.com', name='Ada')

    def test_change_password(self):
        self.client.force_authenticate(self.user)
        wrong = self.client.post('/app/change-password/', {'old_password': 'nope', 'new_password': 'An0ther-strong-one'})
        self.assertEqual(wrong.status_code, 400)
        ok = self.client.post('/app/change-password/', {'old_password': PASSWORD, 'new_password': 'An0ther-strong-one'})
        self.assertEqual(ok.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('An0ther-strong-one'))

    def test_reset_flow(self):
        self.assertEqual(self.client.post('/app/password-reset/', {'email': 'ADA@example.com'}).status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        code = reset_code_from_email()
        self.assertNotIn(code, PasswordResetCode.objects.get().code_hash)

        wrong_code = '000000' if code != '000000' else '111111'
        bad = self.client.post('/app/password-reset/confirm/', {'email': 'ada@example.com', 'code': wrong_code, 'new_password': 'Brand-new-pass-9'})
        self.assertEqual(bad.status_code, 400)

        good = self.client.post('/app/password-reset/confirm/', {'email': 'ada@example.com', 'code': code, 'new_password': 'Brand-new-pass-9'})
        self.assertEqual(good.status_code, 200, good.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Brand-new-pass-9'))

        reused = self.client.post('/app/password-reset/confirm/', {'email': 'ada@example.com', 'code': code, 'new_password': 'Yet-another-pass-9'})
        self.assertEqual(reused.status_code, 400)

    def test_reset_does_not_reveal_unknown_emails_and_has_cooldown(self):
        unknown = self.client.post('/app/password-reset/', {'email': 'nobody@example.com'})
        known = self.client.post('/app/password-reset/', {'email': 'ada@example.com'})
        self.assertEqual((unknown.status_code, unknown.data), (known.status_code, known.data))
        self.client.post('/app/password-reset/', {'email': 'ada@example.com'})
        self.assertEqual(len(mail.outbox), 1)

    def test_code_locks_after_too_many_wrong_attempts(self):
        self.client.post('/app/password-reset/', {'email': 'ada@example.com'})
        code = reset_code_from_email()
        wrong_code = '000000' if code != '000000' else '111111'
        for _ in range(5):
            self.client.post('/app/password-reset/confirm/', {'email': 'ada@example.com', 'code': wrong_code, 'new_password': 'Brand-new-pass-9'})
        locked = self.client.post('/app/password-reset/confirm/', {'email': 'ada@example.com', 'code': code, 'new_password': 'Brand-new-pass-9'})
        self.assertEqual(locked.status_code, 400)


class AccountDeletionTests(APITestCase):
    def test_delete_account_needs_password_and_removes_data(self):
        user = make_user('ada@example.com')
        Gig.objects.create(provider=user, title='T', description='d', category='design')
        self.client.force_authenticate(user)
        self.assertEqual(self.client.post('/app/delete-account/', {'password': 'wrong'}).status_code, 400)
        self.assertEqual(self.client.post('/app/delete-account/', {'password': PASSWORD}).status_code, 200)
        self.assertFalse(User.objects.filter(username='ada@example.com').exists())
        self.assertEqual(Gig.objects.count(), 0)


class SafetyTests(APITestCase):
    def setUp(self):
        self.client_user = make_user('client@example.com', name='Client', role='client')
        self.provider = make_user('provider@example.com', name='Provider')
        self.gig = Gig.objects.create(provider=self.provider, title='Painting', description='Walls', category='home_repairs')

    def test_report(self):
        self.client.force_authenticate(self.client_user)
        res = self.client.post('/app/reports/', {'reported_user': self.provider.id, 'reason': 'scam', 'details': 'Took a deposit'})
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Report.objects.get().reporter, self.client_user)
        mine = self.client.post('/app/reports/', {'reported_user': self.client_user.id, 'reason': 'other'})
        self.assertEqual(mine.status_code, 400)

    def test_block_hides_gigs_and_stops_booking_then_unblock(self):
        self.client.force_authenticate(self.client_user)
        self.assertEqual(len(self.client.get('/app/gigs/').data), 1)

        self.assertEqual(self.client.post('/app/blocks/', {'blocked': self.provider.id}).status_code, 201)
        self.assertEqual(self.client.post('/app/blocks/', {'blocked': self.provider.id}).status_code, 200)
        self.assertEqual(len(self.client.get('/app/gigs/').data), 0)
        self.assertEqual([b['blocked_username'] for b in self.client.get('/app/blocks/').data], ['Provider'])
        booking = self.client.post('/app/bookings/', {'gig': self.gig.id, 'proposed_date': '2030-01-01T00:00:00'})
        self.assertEqual(booking.status_code, 403)

        # The blocked person can no longer open the blocker's profile.
        self.client.force_authenticate(self.provider)
        self.assertEqual(self.client.get(f'/app/provider/{self.client_user.id}/').status_code, 404)

        self.client.force_authenticate(self.client_user)
        self.assertEqual(self.client.delete(f'/app/blocks/{self.provider.id}/').status_code, 204)
        self.assertEqual(Block.objects.count(), 0)
        self.assertEqual(len(self.client.get('/app/gigs/').data), 1)

    def test_phone_only_shared_after_acceptance_and_is_mine_flag(self):
        Profile.objects.filter(user=self.provider).update(phone_number='08011112222')
        self.client.force_authenticate(self.client_user)
        created = self.client.post('/app/bookings/', {'gig': self.gig.id, 'proposed_date': '2030-01-01T00:00:00'})
        self.assertEqual(created.status_code, 201, created.data)
        self.assertIsNone(self.client.get('/app/bookings/mine/').data[0]['provider_phone'])

        booking = Booking.objects.get()
        self.client.force_authenticate(self.provider)
        self.client.patch(f'/app/bookings/{booking.id}/status/', {'status': 'accepted'})

        self.client.force_authenticate(self.client_user)
        self.assertEqual(self.client.get('/app/bookings/mine/').data[0]['provider_phone'], '08011112222')

        convo = self.client.post('/app/conversations/start/', {'booking_id': booking.id}).data
        self.client.post(f"/app/conversations/{convo['id']}/messages/", {'content': 'Hello'})
        self.assertTrue(self.client.get(f"/app/conversations/{convo['id']}/messages/").data[0]['is_mine'])
        self.client.force_authenticate(self.provider)
        self.assertFalse(self.client.get(f"/app/conversations/{convo['id']}/messages/").data[0]['is_mine'])

    def test_ratings_and_counts_follow_reviews(self):
        booking = Booking.objects.create(
            client=self.client_user, provider=self.provider, gig=self.gig, status='completed',
        )

        def snapshot():
            self.client.force_authenticate(self.provider)
            stats = self.client.get('/app/provider-stats/').data
            self.client.force_authenticate(self.client_user)
            page = self.client.get(f'/app/provider/{self.provider.id}/').data
            gig = self.client.get('/app/gigs/').data[0]
            return (stats['reviews'], page['total_reviews'], page['average_rating'],
                    gig['provider_review_count'], gig['provider_rating'])

        self.assertEqual(snapshot(), (0, 0, 0, 0, None))

        self.client.force_authenticate(self.client_user)
        created = self.client.post(f'/app/bookings/{booking.id}/reviews/', {'rating': 4, 'comment': 'Good work'})
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(snapshot(), (1, 1, 4.0, 1, 4.0))

        # A second completed job, reviewed with 5 stars, moves the average.
        second = Booking.objects.create(
            client=self.client_user, provider=self.provider, gig=self.gig, status='completed',
        )
        self.client.force_authenticate(self.client_user)
        self.client.post(f'/app/bookings/{second.id}/reviews/', {'rating': 5})
        self.assertEqual(snapshot(), (2, 2, 4.5, 2, 4.5))

        # Deleting a review takes it back out of the numbers.
        self.client.force_authenticate(self.client_user)
        self.assertEqual(self.client.delete(f"/app/reviews/{created.data['id']}/").status_code, 204)
        self.assertEqual(snapshot(), (1, 1, 5.0, 1, 5.0))

        out_of_range = self.client.post(f'/app/bookings/{booking.id}/reviews/', {'rating': 9})
        self.assertEqual(out_of_range.status_code, 400)


class SubscriptionTests(APITestCase):
    """Free allowance: providers get 3 accepted bookings, clients get 5."""

    def setUp(self):
        self.provider = make_user('provider@example.com', name='Provider')
        Profile.objects.filter(user=self.provider).update(phone_number='08011112222')
        self.gig = Gig.objects.create(provider=self.provider, title='Painting', description='Walls', category='home_repairs')
        self.clients = [make_user(f'client{n}@example.com', name=f'Client {n}', role='client') for n in range(5)]

    def request_booking(self, client, gig=None):
        self.client.force_authenticate(client)
        res = self.client.post('/app/bookings/', {
            'gig': (gig or self.gig).id, 'proposed_date': '2030-01-01T12:00:00', 'message': 'Secret details',
        })
        self.assertEqual(res.status_code, 201, res.data)
        return res.data['id']

    def accept(self, booking_id, as_user=None):
        self.client.force_authenticate(as_user or self.provider)
        return self.client.patch(f'/app/bookings/{booking_id}/status/', {'status': 'accepted'})

    def received(self):
        self.client.force_authenticate(self.provider)
        return {b['id']: b for b in self.client.get('/app/bookings/received/').data}

    def test_provider_gets_three_free_then_requests_lock(self):
        ids = [self.request_booking(c) for c in self.clients[:4]]
        for booking_id in ids[:3]:
            self.assertEqual(self.accept(booking_id).status_code, 200)

        self.client.force_authenticate(self.provider)
        summary = self.client.get('/app/subscription/').data
        self.assertEqual(summary['provider'], {'free_limit': 3, 'used': 3, 'remaining': 0})
        self.assertFalse(summary['is_subscribed'])

        fourth = self.received()[ids[3]]
        self.assertTrue(fourth['locked'])
        self.assertEqual((fourth['client_username'], fourth['message'], fourth['client_phone']), ('A client', '', None))
        # Still enough to tempt: which skill and when.
        self.assertEqual(fourth['gig_title'], 'Painting')
        self.assertFalse(self.received()[ids[0]]['locked'])

        refused = self.accept(ids[3])
        self.assertEqual(refused.status_code, 402)
        self.assertEqual(refused.data['code'], 'subscription_required')
        # Declining is always allowed.
        self.client.force_authenticate(self.provider)
        self.assertEqual(self.client.patch(f'/app/bookings/{ids[3]}/status/', {'status': 'declined'}).status_code, 200)

    def test_subscribing_unlocks_and_expiry_relocks(self):
        from datetime import timedelta
        from django.utils import timezone

        ids = [self.request_booking(c) for c in self.clients[:4]]
        for booking_id in ids[:3]:
            self.accept(booking_id)
        self.assertEqual(self.accept(ids[3]).status_code, 402)

        Profile.objects.filter(user=self.provider).update(is_subscribed=True)
        unlocked = self.received()[ids[3]]
        self.assertFalse(unlocked['locked'])
        self.assertEqual(unlocked['client_username'], 'Client 3')
        self.assertEqual(self.accept(ids[3]).status_code, 200)

        # A lapsed subscription keeps the free three and locks the rest again.
        Profile.objects.filter(user=self.provider).update(subscription_expires=timezone.now() - timedelta(days=1))
        after = self.received()
        self.assertEqual([after[i]['locked'] for i in ids], [False, False, False, True])

    def test_users_cannot_subscribe_themselves(self):
        self.client.force_authenticate(self.provider)
        self.client.patch('/app/profile/', {'is_subscribed': True})
        self.assertFalse(Profile.objects.get(user=self.provider).is_subscribed)

        self.assertEqual(self.client.post('/app/subscription/request/').status_code, 200)
        self.client.post('/app/subscription/request/')
        self.assertTrue(self.client.get('/app/subscription/').data['requested'])
        from .models import SubscriptionRequest
        self.assertEqual(SubscriptionRequest.objects.count(), 1)

    def test_client_sixth_accepted_booking_is_locked(self):
        heavy = self.clients[0]
        booking_ids = []
        # Six different providers each accept one booking from the same client.
        for n in range(6):
            provider = make_user(f'pro{n}@example.com', name=f'Pro {n}')
            Profile.objects.filter(user=provider).update(phone_number=f'0800000000{n}')
            gig = Gig.objects.create(provider=provider, title=f'Job {n}', description='d', category='design')
            booking_id = self.request_booking(heavy, gig)
            self.assertEqual(self.accept(booking_id, as_user=provider).status_code, 200)
            booking_ids.append(booking_id)

        self.client.force_authenticate(heavy)
        mine = {b['id']: b for b in self.client.get('/app/bookings/mine/').data}
        self.assertEqual([mine[i]['locked'] for i in booking_ids], [False] * 5 + [True])
        self.assertEqual(mine[booking_ids[0]]['provider_phone'], '08000000000')
        self.assertIsNone(mine[booking_ids[5]]['provider_phone'])

        self.assertEqual(self.client.post('/app/conversations/start/', {'booking_id': booking_ids[5]}).status_code, 402)
        self.assertIn(self.client.post('/app/conversations/start/', {'booking_id': booking_ids[0]}).status_code, (200, 201))
        self.assertEqual(self.client.get('/app/subscription/').data['client'], {'free_limit': 5, 'used': 5, 'remaining': 0})

    def test_limits_are_settings(self):
        from .models import AppSettings
        config = AppSettings.load()
        config.free_provider_bookings = 1
        config.save()

        ids = [self.request_booking(c) for c in self.clients[:2]]
        self.assertEqual(self.accept(ids[0]).status_code, 200)
        self.assertEqual(self.accept(ids[1]).status_code, 402)
        self.assertEqual(AppSettings.objects.count(), 1)


class PaymentTests(APITestCase):
    """Paystack is faked here; no real request leaves the test."""

    def setUp(self):
        from unittest import mock
        from django.test import override_settings
        from .models import AppSettings

        self.user = make_user('payer@example.com', name='Payer')
        config = AppSettings.load()
        config.standard_price_naira = 2000
        config.subscription_days = 30
        config.save()

        override = override_settings(PAYSTACK_SECRET_KEY='sk_test_fake', FRONTEND_URL='https://example.test')
        override.enable()
        self.addCleanup(override.disable)

        patcher = mock.patch('myapp.payments.requests.request')
        self.paystack = patcher.start()
        self.addCleanup(patcher.stop)

    def reply(self, data, ok=True):
        from unittest import mock
        response = mock.Mock()
        response.json.return_value = {'status': ok, 'message': 'msg', 'data': data}
        self.paystack.return_value = response

    def start(self):
        self.reply({'authorization_url': 'https://checkout.paystack.com/abc', 'access_code': 'abc', 'reference': 'ignored'})
        self.client.force_authenticate(self.user)
        res = self.client.post('/app/subscription/pay/')
        self.assertEqual(res.status_code, 200, res.data)
        return res.data['reference']

    def test_pay_asks_paystack_for_the_right_amount(self):
        from .models import Payment
        reference = self.start()
        sent = self.paystack.call_args.kwargs['json']
        self.assertEqual((sent['amount'], sent['currency'], sent['email']), (200000, 'NGN', 'payer@example.com'))
        self.assertEqual(sent['callback_url'], 'https://example.test/subscribe')
        self.assertEqual(self.paystack.call_args.kwargs['headers']['Authorization'], 'Bearer sk_test_fake')
        self.assertEqual(Payment.objects.get().reference, reference)
        self.assertEqual(self.client.get('/app/subscription/').data['price_text'], '\u20a62,000 for 30 days')
        self.assertEqual(Payment.objects.get().tier, 'standard')

    def test_verify_switches_subscription_on_once(self):
        from datetime import timedelta
        from django.utils import timezone
        reference = self.start()

        self.reply({'status': 'success', 'amount': 200000, 'currency': 'NGN'})
        self.assertEqual(self.client.post('/app/subscription/verify/', {'reference': reference}).data['status'], 'success')
        profile = Profile.objects.get(user=self.user)
        self.assertTrue(profile.is_subscribed)
        first_expiry = profile.subscription_expires
        self.assertAlmostEqual(first_expiry, timezone.now() + timedelta(days=30), delta=timedelta(minutes=1))

        # Verifying the same payment again must not add another month.
        self.client.post('/app/subscription/verify/', {'reference': reference})
        self.assertEqual(Profile.objects.get(user=self.user).subscription_expires, first_expiry)
        self.assertTrue(self.client.get('/app/subscription/').data['is_subscribed'])

        # A second, separate payment extends from the current end date.
        second = self.start()
        self.reply({'status': 'success', 'amount': 200000, 'currency': 'NGN'})
        self.client.post('/app/subscription/verify/', {'reference': second})
        self.assertEqual(Profile.objects.get(user=self.user).subscription_expires, first_expiry + timedelta(days=30))

    def test_underpayment_and_failed_payment_do_not_subscribe(self):
        reference = self.start()
        self.reply({'status': 'success', 'amount': 100, 'currency': 'NGN'})
        self.assertEqual(self.client.post('/app/subscription/verify/', {'reference': reference}).data['status'], 'failed')

        reference = self.start()
        self.reply({'status': 'abandoned', 'amount': 0})
        self.assertEqual(self.client.post('/app/subscription/verify/', {'reference': reference}).data['status'], 'failed')
        self.assertFalse(Profile.objects.get(user=self.user).is_subscribed)

    def test_cannot_verify_someone_elses_payment(self):
        reference = self.start()
        other = make_user('other@example.com')
        self.client.force_authenticate(other)
        self.assertEqual(self.client.post('/app/subscription/verify/', {'reference': reference}).status_code, 400)

    def test_webhook_needs_a_valid_signature(self):
        import hashlib, hmac, json
        reference = self.start()
        self.client.force_authenticate(None)
        body = json.dumps({'event': 'charge.success', 'data': {'reference': reference, 'amount': 200000, 'currency': 'NGN'}})

        forged = self.client.post('/app/paystack/webhook/', body, content_type='application/json', HTTP_X_PAYSTACK_SIGNATURE='nope')
        self.assertEqual(forged.status_code, 401)
        self.assertFalse(Profile.objects.get(user=self.user).is_subscribed)

        signature = hmac.new(b'sk_test_fake', body.encode(), hashlib.sha512).hexdigest()
        real = self.client.post('/app/paystack/webhook/', body, content_type='application/json', HTTP_X_PAYSTACK_SIGNATURE=signature)
        self.assertEqual(real.status_code, 200)
        self.assertTrue(Profile.objects.get(user=self.user).is_subscribed)

    def test_payment_off_without_key_or_price(self):
        from django.test import override_settings
        with override_settings(PAYSTACK_SECRET_KEY=''):
            self.client.force_authenticate(self.user)
            self.assertFalse(self.client.get('/app/subscription/').data['payment_available'])
            self.assertEqual(self.client.post('/app/subscription/pay/').status_code, 503)

    def test_price_follows_the_users_plan(self):
        from .models import AppSettings, Payment
        config = AppSettings.load()
        config.standard_price_naira, config.premium_price_naira, config.client_price_naira = 5000, 15000, 2000
        config.save()

        def plan(user):
            self.client.force_authenticate(user)
            data = self.client.get('/app/subscription/').data
            return data['plan']['tier'], data['plan']['price_naira'], data['price_text']

        client = make_user('booker@example.com', role='client')
        self.assertEqual(plan(client), ('client', 2000, '\u20a62,000 for 30 days'))

        # A provider with no skills yet, then a standard skill, then a premium one.
        self.assertEqual(plan(self.user)[:2], ('standard', 5000))
        Gig.objects.create(provider=self.user, title='Braids', description='d', category='beauty_fashion')
        self.assertEqual(plan(self.user)[:2], ('standard', 5000))
        Gig.objects.create(provider=self.user, title='Roofing', description='d', category='construction')
        self.assertEqual(plan(self.user), ('premium', 15000, '\u20a615,000 for 30 days'))

        # The amount charged comes from the plan, whatever the app sends.
        self.reply({'authorization_url': 'https://checkout.paystack.com/abc'})
        self.client.post('/app/subscription/pay/', {'amount': 1})
        self.assertEqual(self.paystack.call_args.kwargs['json']['amount'], 1500000)
        self.assertEqual(Payment.objects.latest('created_at').tier, 'premium')

        # Premium categories are a setting.
        config.premium_categories = 'automotive'
        config.save()
        self.assertEqual(plan(self.user)[:2], ('standard', 5000))

    def test_standard_subscriber_must_upgrade_for_a_premium_skill(self):
        from datetime import timedelta
        from django.utils import timezone
        Gig.objects.create(provider=self.user, title='Braids', description='d', category='beauty_fashion')
        reference = self.start()
        self.reply({'status': 'success', 'amount': 200000, 'currency': 'NGN'})
        self.client.post('/app/subscription/verify/', {'reference': reference})
        data = self.client.get('/app/subscription/').data
        self.assertEqual((data['is_subscribed'], data['needs_upgrade'], data['current_tier_label']), (True, False, 'Standard'))

        Gig.objects.create(provider=self.user, title='Roofing', description='d', category='construction')
        data = self.client.get('/app/subscription/').data
        self.assertEqual((data['is_subscribed'], data['needs_upgrade'], data['plan']['tier']), (False, True, 'premium'))

        # Paying for Premium starts a fresh 30 days on the higher plan.
        reference = self.start()
        self.reply({'status': 'success', 'amount': 1500000, 'currency': 'NGN'})
        self.client.post('/app/subscription/verify/', {'reference': reference})
        profile = Profile.objects.get(user=self.user)
        self.assertEqual(profile.subscription_tier, 'premium')
        self.assertAlmostEqual(profile.subscription_expires, timezone.now() + timedelta(days=30), delta=timedelta(minutes=1))
        self.assertTrue(self.client.get('/app/subscription/').data['is_subscribed'])

    def test_admin_granted_subscription_covers_every_plan(self):
        Gig.objects.create(provider=self.user, title='Roofing', description='d', category='construction')
        Profile.objects.filter(user=self.user).update(is_subscribed=True)
        self.client.force_authenticate(self.user)
        data = self.client.get('/app/subscription/').data
        self.assertEqual((data['is_subscribed'], data['needs_upgrade']), (True, False))
