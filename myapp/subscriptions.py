"""Free allowance and subscription rules.

Everyone can browse gigs and send booking requests. What a subscription
unlocks is the booking itself:

* A provider can accept a set number of bookings for free. After that, new
  requests still arrive but stay locked (client hidden, cannot accept).
* A client's first few accepted bookings are free. After that, an accepted
  booking stays locked (no contact details or chat) until they subscribe.

What a subscription costs depends on the plan the user needs:

* premium  - a provider with any skill in a premium category
* standard - any other provider
* client   - someone who only books and offers no skills

The allowances, prices and premium categories live in AppSettings and can
be changed in the admin.
"""
from django.utils import timezone

from .models import AppSettings, Booking, Gig, Profile, TIER_RANK

# A booking in one of these states has used one of its owner's free slots.
OPEN_STATUSES = ['accepted', 'completed']

TIER_LABELS = {'client': 'Client', 'standard': 'Standard', 'premium': 'Premium'}


def required_tier(user, config=None):
    """The plan this user needs, judged by their most valuable skill."""
    config = config or AppSettings.load()
    categories = set(Gig.objects.filter(provider=user).values_list('category', flat=True))
    if categories:
        return 'premium' if categories & config.premium_category_set() else 'standard'

    role = Profile.objects.filter(user=user).values_list('role', flat=True).first()
    return 'client' if role == 'client' else 'standard'


def paid_tier(user):
    """The plan of the user's running subscription: a tier name, '' when an
    admin granted it (covers everything), or None when there is none."""
    # Read straight from the database rather than a profile object that may
    # have been loaded before the subscription changed.
    row = Profile.objects.filter(user=user).values(
        'is_subscribed', 'subscription_expires', 'subscription_tier'
    ).first()
    if not row or not row['is_subscribed']:
        return None
    expires = row['subscription_expires']
    if expires is not None and expires <= timezone.now():
        return None
    return row['subscription_tier']


def covers(paid, needed):
    if paid is None:
        return False
    if paid == '':
        return True
    return TIER_RANK[paid] >= TIER_RANK[needed]


def has_subscription(user, config=None):
    """True when the user's subscription is running AND covers the plan they
    need now. A Standard subscriber who adds a Construction skill has to
    upgrade before it counts again."""
    return covers(paid_tier(user), required_tier(user, config))


class LockState:
    """Works out which of one user's bookings are locked. Build one per
    request and reuse it, so a list of bookings costs a handful of queries."""

    def __init__(self, user):
        self.user = user
        self.config = AppSettings.load()
        self.required = required_tier(user, self.config)
        self.paid = paid_tier(user)
        self.subscribed = covers(self.paid, self.required)
        self.limits = {
            'provider': self.config.free_provider_bookings,
            'client': self.config.free_client_bookings,
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
        price = self.config.price_for(self.required)
        days = self.config.subscription_days
        return {
            'is_subscribed': self.subscribed,
            # The plan this user would buy, and what it costs them.
            'plan': {
                'tier': self.required,
                'label': TIER_LABELS[self.required],
                'price_naira': price,
                'days': days,
            },
            'price_text': f'₦{price:,} for {days} days' if price > 0 else '',
            # Paid for a cheaper plan than their skills now need.
            'needs_upgrade': self.paid not in (None, '') and not self.subscribed,
            'current_tier_label': TIER_LABELS.get(self.paid, ''),
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
