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


class Gig(models.Model):
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='gigs'
    )
    title = models.CharField(max_length=120)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    price = models.DecimalField(max_digits=10, decimal_places=2)
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