"""Free allowance and subscription rules.

Everyone can browse gigs and send booking requests. What a subscription
unlocks is the booking itself:

* A provider can accept a set number of bookings for free. After that, new
  requests still arrive but stay locked (client hidden, cannot accept).
* A client's first few accepted bookings are free. After that, an accepted
  booking stays locked (no contact details or chat) until they subscribe.

The two allowances live in AppSettings and can be changed in the admin.
"""
from django.utils import timezone

from .models import AppSettings, Booking, Profile

# A booking in one of these states has used one of its owner's free slots.
OPEN_STATUSES = ['accepted', 'completed']


def has_subscription(user):
    # Read straight from the database rather than a profile object that may
    # have been loaded before an admin switched the subscription on.
    row = Profile.objects.filter(user=user).values('is_subscribed', 'subscription_expires').first()
    if not row or not row['is_subscribed']:
        return False
    expires = row['subscription_expires']
    return expires is None or expires > timezone.now()


class LockState:
    """Works out which of one user's bookings are locked. Build one per
    request and reuse it, so a list of bookings costs a handful of queries."""

    def __init__(self, user):
        self.user = user
        self.subscribed = has_subscription(user)
        config = AppSettings.load()
        self.limits = {
            'provider': config.free_provider_bookings,
            'client': config.free_client_bookings,
        }
        self._open_ids = {}

    def open_ids(self, role):
        """This user's accepted/completed bookings in that role, oldest first."""
        if role not in self._open_ids:
            self._open_ids[role] = list(
                Booking.objects.filter(**{role: self.user}, status__in=OPEN_STATUSES)
                .order_by('created_at', 'id')
                .values_list('id', flat=True)
            )
        return self._open_ids[role]

    def used(self, role):
        return min(len(self.open_ids(role)), self.limits[role])

    def remaining(self, role):
        return max(self.limits[role] - len(self.open_ids(role)), 0)

    def free_ids(self, role):
        return set(self.open_ids(role)[: self.limits[role]])

    def is_locked(self, booking):
        if self.subscribed:
            return False

        if booking.provider_id == self.user.id:
            if booking.status == 'pending':
                # Nothing free left to accept it with.
                return self.remaining('provider') == 0
            if booking.status in OPEN_STATUSES:
                return booking.id not in self.free_ids('provider')
            return False

        if booking.client_id == self.user.id:
            if booking.status in OPEN_STATUSES:
                return booking.id not in self.free_ids('client')
            return False

        return False

    def summary(self):
        return {
            'is_subscribed': self.subscribed,
            'provider': {
                'free_limit': self.limits['provider'],
                'used': self.used('provider'),
                'remaining': self.remaining('provider'),
            },
            'client': {
                'free_limit': self.limits['client'],
                'used': self.used('client'),
                'remaining': self.remaining('client'),
            },
        }


def lock_state_for(context):
    """The LockState for a serializer's request, built once and cached."""
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return None
    if '_lock_state' not in context:
        context['_lock_state'] = LockState(request.user)
    return context['_lock_state']
