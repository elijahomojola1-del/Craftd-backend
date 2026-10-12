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
