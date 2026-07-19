from django.contrib.auth.models import User
from django.db.models import Avg, Count
from rest_framework import serializers

from .models import Gig, Profile, PortfolioImage, Booking, Review, Conversation, Message


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password']

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        return user


class GigSerializer(serializers.ModelSerializer):
    provider_username = serializers.ReadOnlyField(source='provider.username')
    provider_rating = serializers.SerializerMethodField()
    provider_review_count = serializers.SerializerMethodField()

    class Meta:
        model = Gig
        fields = [
            'id', 'provider', 'provider_username', 'title', 'description',
            'category', 'price', 'location', 'image', 'is_active',
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
    username = serializers.ReadOnlyField(source='user.username')
    email = serializers.ReadOnlyField(source='user.email')
    gig_count = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            'id', 'username', 'email', 'bio', 'location', 'phone_number',
            'profile_picture', 'is_verified', 'gig_count',
            'latitude', 'longitude', 'city', 'state',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['is_verified']

    def get_gig_count(self, obj):
        return obj.user.gigs.count()


class PortfolioImageSerializer(serializers.ModelSerializer):
    provider_username = serializers.ReadOnlyField(source='provider.username')

    class Meta:
        model = PortfolioImage
        fields = ['id', 'provider', 'provider_username', 'image', 'caption', 'created_at']
        read_only_fields = ['provider']


class BookingSerializer(serializers.ModelSerializer):
    client_username = serializers.ReadOnlyField(source='client.username')
    provider_username = serializers.ReadOnlyField(source='provider.username')
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

    def get_client_phone(self, obj):
        try:
            return obj.client.profile.phone_number
        except Profile.DoesNotExist:
            return None

    def get_provider_phone(self, obj):
        try:
            return obj.provider.profile.phone_number
        except Profile.DoesNotExist:
            return None

    def get_review_id(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        review = Review.objects.filter(booking=obj, reviewer=request.user).first()
        return review.id if review else None


class ReviewSerializer(serializers.ModelSerializer):
    reviewer_username = serializers.CharField(source='reviewer.username', read_only=True)

    class Meta:
        model = Review
        fields = ['id', 'booking', 'reviewer', 'reviewee', 'rating', 'comment', 'created_at', 'reviewer_username']
        read_only_fields = ['id', 'booking', 'reviewer', 'reviewee', 'created_at']


class NearbyProviderSerializer(serializers.ModelSerializer):
    id = serializers.ReadOnlyField(source='user.id')
    username = serializers.ReadOnlyField(source='user.username')
    distance_km = serializers.FloatField(read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            'id', 'username', 'bio', 'city', 'state',
            'latitude', 'longitude', 'is_verified', 'distance_km',
            'average_rating', 'review_count',
        ]

    def get_average_rating(self, obj):
        result = Review.objects.filter(reviewee=obj.user).aggregate(avg=Avg('rating'))
        avg = result['avg']
        return round(avg, 1) if avg is not None else None

    def get_review_count(self, obj):
        return Review.objects.filter(reviewee=obj.user).count()


class MessageSerializer(serializers.ModelSerializer):
    sender_username = serializers.ReadOnlyField(source='sender.username')

    class Meta:
        model = Message
        fields = ['id', 'conversation', 'sender', 'sender_username', 'content', 'is_read', 'created_at']
        read_only_fields = ['conversation', 'sender', 'is_read', 'created_at']  # ← fix


class ConversationSerializer(serializers.ModelSerializer):
    client_username = serializers.ReadOnlyField(source='client.username')
    provider_username = serializers.ReadOnlyField(source='provider.username')
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
        return other.username if other else None

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