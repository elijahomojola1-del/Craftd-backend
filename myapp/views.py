import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db.models import F, ExpressionWrapper, FloatField, Avg, Q
from django.db.models.functions import Radians, Sin, Cos, ATan2, Sqrt
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import generics
from rest_framework.response import Response
from rest_framework.permissions import (
    AllowAny, BasePermission, IsAuthenticated, IsAuthenticatedOrReadOnly, SAFE_METHODS,
)
from rest_framework.exceptions import ValidationError, PermissionDenied

from .models import (
    AppSettings, Block, Booking, Conversation, Gig, MAX_GIGS_PER_PROVIDER, Message,
    PasswordResetCode, PortfolioImage, Profile, Report, Review, SubscriptionRequest,
    public_name,
)
from .serializers import (
    RegisterSerializer,
    GigSerializer,
    ProfileSerializer,
    PortfolioImageSerializer,
    BookingSerializer,
    ReviewSerializer,
    NearbyProviderSerializer,
    ConversationSerializer,
    MessageSerializer,
    ReportSerializer,
    BlockSerializer,
    check_password_strength,
)
from .push_notifications import send_push_notification, send_sms
from .subscriptions import LockState
from . import payments

User = get_user_model()

SUBSCRIPTION_REQUIRED = {
    'detail': 'You have used your free bookings. Subscribe to unlock this one.',
    'code': 'subscription_required',
}

RESET_CODE_LIFETIME = timedelta(minutes=15)
RESET_CODE_COOLDOWN = timedelta(seconds=60)
RESET_CODE_MAX_ATTEMPTS = 5


def blocked_user_ids(user):
    """Ids of everyone this user has blocked or been blocked by."""
    if not user or not user.is_authenticated:
        return set()
    pairs = Block.objects.filter(Q(blocker=user) | Q(blocked=user)).values_list('blocker_id', 'blocked_id')
    ids = set()
    for blocker_id, blocked_id in pairs:
        ids.add(blocked_id if blocker_id == user.id else blocker_id)
    return ids


def is_blocked_between(user, other):
    return Block.objects.filter(
        Q(blocker=user, blocked=other) | Q(blocker=other, blocked=user)
    ).exists()


class IsProviderOrReadOnly(BasePermission):
    """Anyone may read a gig; only the provider who owns it may change it."""

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_authenticated and obj.provider_id == request.user.id


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer


class GigListCreateView(generics.ListCreateAPIView):
    serializer_class = GigSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        params = self.request.query_params

        if params.get('mine') == 'true':
            if not self.request.user.is_authenticated:
                return Gig.objects.none()
            return Gig.objects.filter(provider=self.request.user).order_by('-created_at')

        queryset = Gig.objects.filter(is_active=True)

        hidden = blocked_user_ids(self.request.user)
        if hidden:
            queryset = queryset.exclude(provider_id__in=hidden)

        category = params.get('category')
        if category:
            queryset = queryset.filter(category=category)

        search = (params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(description__icontains=search)
                | Q(location__icontains=search)
                | Q(category__icontains=search.replace(' ', '_'))
            )

        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        if Gig.objects.filter(provider=self.request.user).count() >= MAX_GIGS_PER_PROVIDER:
            raise ValidationError(
                f"You can only have {MAX_GIGS_PER_PROVIDER} skills at a time. Remove one before adding another."
            )
        serializer.save(provider=self.request.user)


class GigDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Gig.objects.all()
    serializer_class = GigSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsProviderOrReadOnly]


class NearbyProvidersView(generics.ListAPIView):
    serializer_class = NearbyProviderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        lat = self.request.query_params.get('lat')
        lng = self.request.query_params.get('lng')
        radius_km = self.request.query_params.get('radius', 15)

        if not lat or not lng:
            raise ValidationError("lat and lng query params are required.")

        try:
            lat = float(lat)
            lng = float(lng)
            radius_km = float(radius_km)
        except ValueError:
            raise ValidationError("lat, lng and radius must be numbers.")

        queryset = Profile.objects.exclude(
            latitude__isnull=True
        ).exclude(
            longitude__isnull=True
        ).exclude(
            user=self.request.user
        ).exclude(
            user_id__in=blocked_user_ids(self.request.user)
        ).filter(
            # Only people who actually offer a service are "providers".
            user__gigs__is_active=True
        ).distinct().annotate(
            distance_km=ExpressionWrapper(
                6371 * 2 * ATan2(
                    Sqrt(
                        Sin(Radians(F('latitude') - lat) / 2) ** 2 +
                        Cos(Radians(lat)) * Cos(Radians(F('latitude'))) *
                        Sin(Radians(F('longitude') - lng) / 2) ** 2
                    ),
                    Sqrt(1 - (
                        Sin(Radians(F('latitude') - lat) / 2) ** 2 +
                        Cos(Radians(lat)) * Cos(Radians(F('latitude'))) *
                        Sin(Radians(F('longitude') - lng) / 2) ** 2
                    ))
                ),
                output_field=FloatField()
            )
        ).filter(distance_km__lte=radius_km).order_by('distance_km')

        return queryset


class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return profile


class SavePushTokenView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        push_token = request.data.get('push_token')

        if not push_token:
            return Response({'detail': 'push_token is required.'}, status=400)

        profile, created = Profile.objects.get_or_create(user=request.user)
        profile.push_token = push_token
        profile.save()

        return Response({'detail': 'Push token saved successfully.'})


class PortfolioImageListCreateView(generics.ListCreateAPIView):
    serializer_class = PortfolioImageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return PortfolioImage.objects.filter(provider=self.request.user)

    def perform_create(self, serializer):
        serializer.save(provider=self.request.user)


class PortfolioImageDeleteView(generics.DestroyAPIView):
    serializer_class = PortfolioImageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return PortfolioImage.objects.filter(provider=self.request.user)


class BookingCreateView(generics.CreateAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        gig = serializer.validated_data['gig']

        if gig.provider_id == self.request.user.id:
            raise ValidationError("You can't book your own skill.")
        if is_blocked_between(self.request.user, gig.provider):
            raise PermissionDenied("You can't book this provider.")

        booking = serializer.save(client=self.request.user, provider=gig.provider)
        client_name = public_name(self.request.user)

        try:
            provider_profile = Profile.objects.get(user=gig.provider)

            if provider_profile.push_token:
                send_push_notification(
                    push_token=provider_profile.push_token,
                    title='New Booking Request',
                    body=f'{client_name} wants to book "{gig.title}"',
                    data={'booking_id': booking.id, 'type': 'new_booking'},
                )

            if provider_profile.phone_number:
                send_sms(
                    phone_number=provider_profile.phone_number,
                    message=f'CRAFTD: {client_name} wants to book "{gig.title}". Open the app to respond.',
                )
        except Profile.DoesNotExist:
            pass


class MyBookingsView(generics.ListAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(client=self.request.user)


class ReceivedBookingsView(generics.ListAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(provider=self.request.user)


class BookingStatusUpdateView(generics.UpdateAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    queryset = Booking.objects.all()

    def get_queryset(self):
        return Booking.objects.filter(
            Q(provider=self.request.user) | Q(client=self.request.user)
        )

    def patch(self, request, *args, **kwargs):
        booking = self.get_object()
        new_status = request.data.get('status')

        if new_status not in ['accepted', 'declined', 'completed', 'cancelled']:
            return Response({'detail': 'Invalid status'}, status=400)

        if new_status in ['accepted', 'declined', 'completed'] and request.user != booking.provider:
            return Response({'detail': 'Only the provider can do that.'}, status=403)
        if new_status == 'cancelled' and request.user != booking.client:
            return Response({'detail': 'Only the client can cancel.'}, status=403)

        # Out of free bookings: the provider must subscribe to accept more.
        if new_status == 'accepted' and LockState(request.user).is_locked(booking):
            return Response(SUBSCRIPTION_REQUIRED, status=402)

        booking.status = new_status
        booking.save()

        status_messages = {
            'accepted': f'Your booking for "{booking.gig.title}" was accepted!',
            'declined': f'Your booking for "{booking.gig.title}" was declined.',
            'completed': f'Your booking for "{booking.gig.title}" is marked complete.',
        }

        if new_status in status_messages:
            try:
                client_profile = Profile.objects.get(user=booking.client)

                if client_profile.push_token:
                    send_push_notification(
                        push_token=client_profile.push_token,
                        title='Booking Update',
                        body=status_messages[new_status],
                        data={'booking_id': booking.id, 'type': f'booking_{new_status}'},
                    )

                if client_profile.phone_number:
                    send_sms(
                        phone_number=client_profile.phone_number,
                        message=f'CRAFTD: {status_messages[new_status]}',
                    )
            except Profile.DoesNotExist:
                pass

        serializer = self.get_serializer(booking)
        return Response(serializer.data)


class BookingDeleteView(generics.DestroyAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(
            Q(client=self.request.user) | Q(provider=self.request.user)
        )


class ReviewCreateView(generics.CreateAPIView):
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        booking = get_object_or_404(Booking, pk=self.kwargs['pk'])
        user = self.request.user

        if booking.status != 'completed':
            raise ValidationError("You can only review completed bookings.")

        if user not in [booking.client, booking.provider]:
            raise PermissionDenied("You are not part of this booking.")

        reviewee = booking.provider if user == booking.client else booking.client

        if Review.objects.filter(booking=booking, reviewer=user).exists():
            raise ValidationError("You've already reviewed this booking.")

        serializer.save(booking=booking, reviewer=user, reviewee=reviewee)


class ReviewDeleteView(generics.DestroyAPIView):
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Review.objects.filter(reviewer=self.request.user)


class ProviderReviewListView(generics.ListAPIView):
    serializer_class = ReviewSerializer

    def get_queryset(self):
        provider_id = self.kwargs.get('pk') or self.kwargs.get('user_id')
        return Review.objects.filter(reviewee_id=provider_id).order_by('-created_at')


class ProviderDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        provider = get_object_or_404(User, pk=pk)
        profile = get_object_or_404(Profile, user=provider)

        if Block.objects.filter(blocker=provider, blocked=request.user).exists():
            return Response({'detail': 'This profile is not available.'}, status=404)

        gigs = provider.gigs.filter(is_active=True)
        reviews = Review.objects.filter(reviewee=provider)
        avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0

        data = {
            'id': provider.id,
            'username': public_name(provider),
            'bio': profile.bio,
            'location': profile.location,
            'city': profile.city,
            'state': profile.state,
            'profile_picture': request.build_absolute_uri(profile.profile_picture.url) if profile.profile_picture else None,
            'is_verified': profile.is_verified,
            'average_rating': round(avg_rating, 1),
            'total_reviews': reviews.count(),
            'is_blocked': Block.objects.filter(blocker=request.user, blocked=provider).exists(),
            'is_me': provider.id == request.user.id,
            'gigs': GigSerializer(gigs, many=True, context={'request': request}).data,
            'portfolio': PortfolioImageSerializer(provider.portfolio_images.all(), many=True, context={'request': request}).data,
        }
        return Response(data)


class ProviderStatsView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        jobs_done = Booking.objects.filter(provider=user, status='completed').count()
        reviews_count = Review.objects.filter(reviewee=user).count()

        return Response({
            'jobs_done': jobs_done,
            'reviews': reviews_count,
        })


class ConversationListView(generics.ListAPIView):
    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        hidden = blocked_user_ids(user)
        return Conversation.objects.filter(
            Q(client=user) | Q(provider=user)
        ).exclude(
            Q(client_id__in=hidden) | Q(provider_id__in=hidden)
        ).order_by('-updated_at')

    def get_serializer_context(self):
        return {'request': self.request}


class ConversationStartView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        booking_id = request.data.get('booking_id')
        if not booking_id:
            return Response({'detail': 'booking_id is required.'}, status=400)

        booking = get_object_or_404(Booking, pk=booking_id)

        if request.user not in [booking.client, booking.provider]:
            return Response({'detail': 'You are not part of this booking.'}, status=403)

        if booking.status not in ['accepted', 'completed']:
            return Response(
                {'detail': 'Messaging is only available once the provider has accepted this booking.'},
                status=403,
            )

        if is_blocked_between(booking.client, booking.provider):
            return Response({'detail': "You can't message this person."}, status=403)

        if LockState(request.user).is_locked(booking):
            return Response(SUBSCRIPTION_REQUIRED, status=402)

        conversation, created = Conversation.objects.get_or_create(
            booking=booking,
            defaults={'client': booking.client, 'provider': booking.provider},
        )

        serializer = ConversationSerializer(conversation, context={'request': request})
        return Response(serializer.data, status=201 if created else 200)


class MessageListCreateView(generics.ListCreateAPIView):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]

    def get_conversation(self):
        conversation = get_object_or_404(Conversation, pk=self.kwargs['pk'])
        if self.request.user not in [conversation.client, conversation.provider]:
            raise PermissionDenied("You are not part of this conversation.")
        if conversation.booking and LockState(self.request.user).is_locked(conversation.booking):
            raise PermissionDenied(SUBSCRIPTION_REQUIRED['detail'])
        return conversation

    def get_queryset(self):
        conversation = self.get_conversation()

        Message.objects.filter(
            conversation=conversation, is_read=False
        ).exclude(sender=self.request.user).update(is_read=True)

        return Message.objects.filter(conversation=conversation)

    def perform_create(self, serializer):
        conversation = self.get_conversation()

        if conversation.booking and conversation.booking.status not in ['accepted', 'completed']:
            raise PermissionDenied("This booking is no longer accepting messages.")

        if is_blocked_between(conversation.client, conversation.provider):
            raise PermissionDenied("You can't message this person.")

        message = serializer.save(conversation=conversation, sender=self.request.user)

        conversation.save()

        recipient = conversation.provider if self.request.user == conversation.client else conversation.client

        try:
            recipient_profile = Profile.objects.get(user=recipient)
            if recipient_profile.push_token:
                send_push_notification(
                    push_token=recipient_profile.push_token,
                    title=f'New message from {public_name(self.request.user)}',
                    body=message.content[:100],
                    data={'conversation_id': conversation.id, 'type': 'new_message'},
                )
        except Profile.DoesNotExist:
            pass


# ---------------------------------------------------------------------------
# Account: passwords and deletion
# ---------------------------------------------------------------------------

class ChangePasswordView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        old_password = request.data.get('old_password') or ''
        new_password = request.data.get('new_password') or ''

        if not request.user.check_password(old_password):
            return Response({'detail': 'Your current password is incorrect.'}, status=400)

        check_password_strength(new_password, user=request.user)
        request.user.set_password(new_password)
        request.user.save()
        return Response({'detail': 'Your password has been changed.'})


class PasswordResetRequestView(generics.GenericAPIView):
    permission_classes = [AllowAny]

    # The reply is the same whether or not the email belongs to an account,
    # so this can't be used to find out who is registered.
    reply = {'detail': 'If that email has an account, we have sent it a 6-digit code.'}

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        user = User.objects.filter(email__iexact=email).first() if email else None

        if user:
            recent = PasswordResetCode.objects.filter(
                user=user, created_at__gte=timezone.now() - RESET_CODE_COOLDOWN
            ).exists()
            if not recent:
                code = f'{secrets.randbelow(1000000):06d}'
                PasswordResetCode.objects.filter(user=user, used=False).update(used=True)
                PasswordResetCode.objects.create(user=user, code_hash=make_password(code))
                try:
                    send_mail(
                        subject='Your CRAFTD password reset code',
                        message=(
                            f'Your CRAFTD password reset code is {code}.\n\n'
                            'It expires in 15 minutes. If you did not ask for this, '
                            'you can ignore this email and your password will stay the same.'
                        ),
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                        recipient_list=[user.email],
                    )
                except Exception as exc:  # mail server unreachable or misconfigured
                    print(f'Password reset email failed: {exc}')

        return Response(self.reply)


class PasswordResetConfirmView(generics.GenericAPIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        code = (request.data.get('code') or '').strip()
        new_password = request.data.get('new_password') or ''
        invalid = Response({'detail': 'That code is wrong or has expired. Request a new one.'}, status=400)

        user = User.objects.filter(email__iexact=email).first() if email else None
        if not user:
            return invalid

        reset = PasswordResetCode.objects.filter(
            user=user, used=False, created_at__gte=timezone.now() - RESET_CODE_LIFETIME
        ).first()
        if not reset or reset.attempts >= RESET_CODE_MAX_ATTEMPTS:
            return invalid

        if not check_password(code, reset.code_hash):
            reset.attempts += 1
            reset.save(update_fields=['attempts'])
            return invalid

        check_password_strength(new_password, user=user)
        user.set_password(new_password)
        user.save()
        reset.used = True
        reset.save(update_fields=['used'])
        return Response({'detail': 'Your password has been reset. You can log in now.'})


class DeleteAccountView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.check_password(request.data.get('password') or ''):
            return Response({'detail': 'Your password is incorrect.'}, status=400)

        # Cascades to the profile, gigs, bookings, reviews, messages and photos.
        request.user.delete()
        return Response({'detail': 'Your account has been deleted.'})


# ---------------------------------------------------------------------------
# Safety: reports and blocks
# ---------------------------------------------------------------------------

class ReportCreateView(generics.CreateAPIView):
    serializer_class = ReportSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        if serializer.validated_data['reported_user'] == self.request.user:
            raise ValidationError("You can't report yourself.")
        serializer.save(reporter=self.request.user)


class BlockListCreateView(generics.ListCreateAPIView):
    serializer_class = BlockSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Block.objects.filter(blocker=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        blocked = serializer.validated_data['blocked']

        if blocked == request.user:
            raise ValidationError("You can't block yourself.")

        block, created = Block.objects.get_or_create(blocker=request.user, blocked=blocked)
        return Response(self.get_serializer(block).data, status=201 if created else 200)


class BlockDeleteView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, user_id):
        Block.objects.filter(blocker=request.user, blocked_id=user_id).delete()
        return Response(status=204)


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

class SubscriptionView(generics.GenericAPIView):
    """Where the signed-in user stands: subscribed or not, and how many free
    bookings they have left as a provider and as a client."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = LockState(request.user).summary()
        data['expires'] = (
            Profile.objects.filter(user=request.user).values_list('subscription_expires', flat=True).first()
        )
        # False until a Paystack key and a price are set; the app then falls
        # back to "request a subscription".
        data['payment_available'] = payments.payment_available(request.user)
        data['requested'] = SubscriptionRequest.objects.filter(user=request.user, handled=False).exists()
        return Response(data)


class SubscriptionRequestView(generics.GenericAPIView):
    """Records that the user wants to subscribe. Online payment is not
    connected yet, so an admin follows up and switches it on."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        SubscriptionRequest.objects.get_or_create(user=request.user, handled=False)
        return Response({'detail': "Thanks. We have your request and will be in touch to set up your subscription."})


# ---------------------------------------------------------------------------
# Paying for a subscription (Paystack)
# ---------------------------------------------------------------------------

class SubscriptionPayView(generics.GenericAPIView):
    """Starts a payment and returns the Paystack checkout address to open."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            return Response(payments.start_payment(request.user))
        except payments.PaymentError as exc:
            return Response({'detail': str(exc)}, status=503)


class SubscriptionVerifyView(generics.GenericAPIView):
    """Called when the user comes back from the checkout page."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        reference = (request.data.get('reference') or '').strip()
        if not reference:
            return Response({'detail': 'reference is required.'}, status=400)
        try:
            payment = payments.verify_payment(request.user, reference)
        except payments.PaymentError as exc:
            return Response({'detail': str(exc)}, status=400)
        return Response({'status': payment.status})


class PaystackWebhookView(generics.GenericAPIView):
    """Paystack calls this itself when a payment succeeds, so a subscription
    still switches on if the user closes the page before returning."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        signature = request.headers.get('x-paystack-signature', '')
        if not payments.valid_signature(request.body, signature):
            return Response(status=401)

        event = request.data.get('event')
        data = request.data.get('data') or {}
        if event == 'charge.success' and data.get('reference'):
            payments.apply_payment(data['reference'], data.get('amount', 0), data.get('currency', 'NGN'))
        return Response(status=200)
