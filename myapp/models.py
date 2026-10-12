from django.conf import settings
from django.db import models


CATEGORY_CHOICES = [
    ('design', 'Design'),
    ('development', 'Development'),
    ('writing', 'Writing'),
    ('tutoring', 'Tutoring'),
    ('marketing', 'Marketing'),
    ('business_support', 'Business support'),
    ('home_repairs', 'Home repairs'),
    ('cleaning', 'Cleaning'),
    ('construction', 'Construction'),
    ('automotive', 'Automotive'),
    ('beauty_fashion', 'Beauty and fashion'),
    ('events', 'Events'),
    ('transport_errands', 'Transport and errands'),
    ('health_fitness', 'Health and fitness'),
]

BOOKING_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('accepted', 'Accepted'),
    ('declined', 'Declined'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled'),
]


ROLE_CHOICES = [
    ('client', 'Client'),
    ('provider', 'Provider'),
]

MAX_GIGS_PER_PROVIDER = 3

# Subscription plans, cheapest first. A higher plan covers the ones below it.
TIER_CHOICES = [
    ('client', 'Client'),
    ('standard', 'Standard'),
    ('premium', 'Premium'),
]
TIER_RANK = {'client': 0, 'standard': 1, 'premium': 2}


class Gig(models.Model):
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='gigs'
    )
    title = models.CharField(max_length=120)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    # Prices are agreed in chat and no longer listed; kept for old records.
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    location = models.CharField(max_length=120, blank=True)
    image = models.ImageField(upload_to='gig_images/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile'
    )
    push_token = models.CharField(max_length=255, blank=True, null=True)
    # Shown to other users in place of the account's email address.
    display_name = models.CharField(max_length=80, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='provider')
    # Switched on by an admin (or by payment, once connected). An empty
    # expiry date means the subscription does not run out.
    is_subscribed = models.BooleanField(default=False)
    subscription_expires = models.DateTimeField(blank=True, null=True)
    # Which plan was paid for. Empty means an admin granted it, which covers
    # every plan.
    subscription_tier = models.CharField(max_length=10, choices=TIER_CHOICES, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    location = models.CharField(max_length=120, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    profile_picture = models.ImageField(upload_to='profile_pictures/', blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s profile"


def public_name(user):
    """The name other users see: the chosen display name, never the full email."""
    try:
        name = user.profile.display_name.strip()
    except Profile.DoesNotExist:
        name = ''
    return name or user.username.split('@')[0]


class PortfolioImage(models.Model):
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='portfolio_images'
    )
    image = models.ImageField(upload_to='portfolio_images/')
    caption = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.provider.username} - {self.caption or 'portfolio image'}"


class Booking(models.Model):
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings_made'
    )
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings_received'
    )
    gig = models.ForeignKey(Gig, on_delete=models.CASCADE, related_name='bookings')
    status = models.CharField(max_length=20, choices=BOOKING_STATUS_CHOICES, default='pending')
    message = models.TextField(blank=True)
    proposed_date = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Booking #{self.id} - {self.gig.title}"


class Review(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='reviews')
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews_given'
    )
    reviewee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews_received'
    )
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('booking', 'reviewer')

    def __str__(self):
        return f"Review by {self.reviewer.username} for {self.reviewee.username}"


class Conversation(models.Model):
    booking = models.OneToOneField(
        Booking, on_delete=models.CASCADE, related_name='conversation', null=True, blank=True
    )
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversations_as_client'
    )
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversations_as_provider'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ('client', 'provider', 'booking')

    def __str__(self):
        return f"Conversation: {self.client.username} & {self.provider.username}"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='messages_sent'
    )
    content = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender.username}: {self.content[:30]}"

REPORT_REASON_CHOICES = [
    ('scam', 'Scam or fraud'),
    ('abuse', 'Abuse or harassment'),
    ('fake', 'Fake profile or listing'),
    ('no_show', 'Did not show up'),
    ('other', 'Something else'),
]


class Report(models.Model):
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reports_made'
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reports_received'
    )
    reason = models.CharField(max_length=20, choices=REPORT_REASON_CHOICES)
    details = models.TextField(max_length=1000, blank=True)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reporter.username} reported {self.reported_user.username} ({self.reason})"


class Block(models.Model):
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocks_made'
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocks_received'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('blocker', 'blocked')

    def __str__(self):
        return f"{self.blocker.username} blocked {self.blocked.username}"


class PasswordResetCode(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='password_reset_codes'
    )
    # Only a hash of the emailed code is kept.
    code_hash = models.CharField(max_length=128)
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Password reset for {self.user.username}"


class AppSettings(models.Model):
    """One row of business settings, editable in the admin without new code."""

    free_provider_bookings = models.PositiveIntegerField(
        default=3,
        help_text="How many bookings a provider can accept before needing a subscription.",
    )
    free_client_bookings = models.PositiveIntegerField(
        default=5,
        help_text="How many accepted bookings a client can open before needing a subscription.",
    )
    standard_price_naira = models.PositiveIntegerField(
        default=5000,
        help_text="Subscription price, in naira, for providers whose skills are all in standard categories.",
    )
    premium_price_naira = models.PositiveIntegerField(
        default=15000,
        help_text="Subscription price, in naira, for providers with a skill in a premium category.",
    )
    client_price_naira = models.PositiveIntegerField(
        default=2000,
        help_text="Subscription price, in naira, for people who only book and offer no skills.",
    )
    premium_categories = models.CharField(
        max_length=300,
        default='construction,automotive,home_repairs,events,development',
        help_text=(
            "Categories charged the premium price, separated by commas. Use the category codes: "
            + ", ".join(code for code, _ in CATEGORY_CHOICES)
        ),
    )
    subscription_days = models.PositiveIntegerField(
        default=30,
        help_text="How many days one payment buys.",
    )

    def premium_category_set(self):
        return {code.strip() for code in self.premium_categories.split(',') if code.strip()}

    def price_for(self, tier):
        return {
            'client': self.client_price_naira,
            'standard': self.standard_price_naira,
            'premium': self.premium_price_naira,
        }[tier]

    class Meta:
        verbose_name = "App settings"
        verbose_name_plural = "App settings"

    def __str__(self):
        return "App settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # only ever one row
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SubscriptionRequest(models.Model):
    """Someone tapped "Subscribe". Until online payment exists, an admin
    follows up and switches the subscription on from the Profile page."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscription_requests'
    )
    handled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} wants to subscribe"


class Payment(models.Model):
    """One attempt to pay for a subscription through Paystack."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payments'
    )
    reference = models.CharField(max_length=64, unique=True)
    amount_kobo = models.PositiveIntegerField()
    days = models.PositiveIntegerField()
    tier = models.CharField(max_length=10, choices=TIER_CHOICES, default='standard')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} {self.reference} ({self.status})"
