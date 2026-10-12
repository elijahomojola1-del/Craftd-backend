from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Avg
from rest_framework import serializers

from .models import (
    Block, Booking, Conversation, Gig, Message, PortfolioImage, Profile, Report,
    Review, ROLE_CHOICES, public_name,
)


def check_password_strength(password, user=None):
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages))
    return password


class PublicNameField(serializers.ReadOnlyField):
    """Renders a related user as the name other people may see."""

    def to_representation(self, value):
        return public_name(value)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    email = serializers.EmailField()
    display_name = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=80)
    role = serializers.ChoiceField(write_only=True, required=False, choices=ROLE_CHOICES)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password', 'display_name', 'role']

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_username(self, value):
        return value.strip().lower()

    def validate_password(self, value):
        return check_password_strength(value)

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        Profile.objects.update_or_create(
            user=user,
            defaults={
                'display_name': validated_data.get('display_name', '').strip(),
                'role': validated_data.get('role', 'provider'),
            },
        )
        return user


class GigSerializer(serializers.ModelSerializer):
    provider_username = PublicNameField(source='provider')
    provider_rating = serializers.SerializerMethodField()
    provider_review_count = serializers.SerializerMethodField()

    class Meta:
        model = Gig
        fields = [
            'id', 'provider', 'provider_username', 'title', 'description',
            'category', 'location', 'image', 'is_active',
            'provider_rating', 'provider_review_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['provider']

    def get_provider_rating(self, obj):
        result = Review.objects.filter(reviewee=obj.provider).aggregate(avg=Avg('rating'))
        avg = result['avg']
        return round(avg, 1) if avg is not None else None

    def get_provider_review_count(self, obj):
        return Review.objects.filter(reviewee=obj.provider).count()


class ProfileSerializer(serializers.ModelSerializer):
    username = PublicNameField(source='user')
    email = serializers.ReadOnlyField(source='user.email')
    gig_count = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            'id', 'username', 'display_name', 'role', 'email', 'bio', 'location',
            'phone_number', 'profile_picture', 'is_verified', 'gig_count',
            'latitude', 'longitude', 'city', 'state',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['is_verified']

    def get_gig_count(self, obj):
        return obj.user.gigs.count()


class PortfolioImageSerializer(serializers.ModelSerializer):
    provider_username = PublicNameField(source='provider')

    class Meta:
        model = PortfolioImage
        fields = ['id', 'provider', 'provider_username', 'image', 'caption', 'created_at']
        read_only_fields = ['provider']


class BookingSerializer(serializers.ModelSerializer):
    client_username = PublicNameField(source='client')
    provider_username = PublicNameField(source='provider')
    gig_title = serializers.ReadOnlyField(source='gig.title')
    gig_image = serializers.ImageField(source='gig.image', read_only=True)
    client_phone = serializers.SerializerMethodField()
    provider_phone = serializers.SerializerMethodField()
    review_id = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id', 'client', 'client_username', 'client_phone',
            'provider', 'provider_username', 'provider_phone',
            'gig', 'gig_title', 'gig_image', 'status', 'message',
            'proposed_date', 'created_at', 'updated_at', 'review_id',
        ]
        read_only_fields = ['client', 'provider', 'status']

    def _phone_once_accepted(self, obj, user):
        # Phone numbers are only shared once the provider has accepted.
        if obj.status not in ['accepted', 'completed']:
            return None
        try:
            return user.profile.phone_number
        except Profile.DoesNotExist:
            return None

    def get_client_phone(self, obj):
        return self._phone_once_accepted(obj, obj.client)

    def get_provider_phone(self, obj):
        return self._phone_once_accepted(obj, obj.provider)

    def get_review_id(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        review = Review.objects.filter(booking=obj, reviewer=request.user).first()
        return review.id if review else None


class ReviewSerializer(serializers.ModelSerializer):
    reviewer_username = PublicNameField(source='reviewer')

    class Meta:
        model = Review
        fields = ['id', 'booking', 'reviewer', 'reviewee', 'rating', 'comment', 'created_at', 'reviewer_username']
        read_only_fields = ['id', 'booking', 'reviewer', 'reviewee', 'created_at']

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value


class NearbyProviderSerializer(serializers.ModelSerializer):
    id = serializers.ReadOnlyField(source='user.id')
    username = PublicNameField(source='user')
    distance_km = serializers.FloatField(read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            'id', 'username', 'bio', 'city', 'state',
            'is_verified', 'distance_km',
            'average_rating', 'review_count',
        ]

    def get_average_rating(self, obj):
        result = Review.objects.filter(reviewee=obj.user).aggregate(avg=Avg('rating'))
        avg = result['avg']
        return round(avg, 1) if avg is not None else None

    def get_review_count(self, obj):
        return Review.objects.filter(reviewee=obj.user).count()


class MessageSerializer(serializers.ModelSerializer):
    sender_username = PublicNameField(source='sender')
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ['id', 'conversation', 'sender', 'sender_username', 'is_mine', 'content', 'is_read', 'created_at']
        read_only_fields = ['conversation', 'sender', 'is_read', 'created_at']

    def get_is_mine(self, obj):
        request = self.context.get('request')
        return bool(request and request.user.is_authenticated and obj.sender_id == request.user.id)


class ConversationSerializer(serializers.ModelSerializer):
    client_username = PublicNameField(source='client')
    provider_username = PublicNameField(source='provider')
    other_user_id = serializers.SerializerMethodField()
    other_username = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'booking', 'client', 'client_username',
            'provider', 'provider_username', 'other_user_id',
            'other_username', 'last_message', 'unread_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['client', 'provider']

    def get_other_user(self, obj):
        request = self.context.get('request')
        if not request:
            return None
        return obj.provider if request.user == obj.client else obj.client

    def get_other_user_id(self, obj):
        other = self.get_other_user(obj)
        return other.id if other else None

    def get_other_username(self, obj):
        other = self.get_other_user(obj)
        return public_name(other) if other else None

    def get_last_message(self, obj):
        last = obj.messages.order_by('-created_at').first()
        if not last:
            return None
        return {
            'content': last.content,
            'sender_id': last.sender_id,
            'created_at': last.created_at,
        }

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 0
        return obj.messages.filter(is_read=False).exclude(sender=request.user).count()


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = ['id', 'reported_user', 'reason', 'details', 'created_at']
        read_only_fields = ['id', 'created_at']


class BlockSerializer(serializers.ModelSerializer):
    blocked_username = PublicNameField(source='blocked')

    class Meta:
        model = Block
        fields = ['id', 'blocked', 'blocked_username', 'created_at']
        read_only_fields = ['id', 'created_at']
