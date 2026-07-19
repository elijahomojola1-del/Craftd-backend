from django.contrib.auth import get_user_model
from django.db.models import F, ExpressionWrapper, FloatField, Avg, Q
from django.db.models.functions import Radians, Sin, Cos, ATan2, Sqrt
from django.shortcuts import get_object_or_404

from rest_framework import generics
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticatedOrReadOnly, IsAuthenticated
from rest_framework.exceptions import ValidationError, PermissionDenied

from .models import Gig, Profile, PortfolioImage, Booking, Review, Conversation, Message
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
)
from .push_notifications import send_push_notification, send_sms

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer


class GigListCreateView(generics.ListCreateAPIView):
    serializer_class = GigSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        if self.request.query_params.get('mine') == 'true':
            return Gig.objects.filter(provider=self.request.user).order_by('-created_at')
        return Gig.objects.filter(is_active=True).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(provider=self.request.user)


class GigDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Gig.objects.all()
    serializer_class = GigSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class NearbyProvidersView(generics.ListAPIView):
    serializer_class = NearbyProviderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        lat = self.request.query_params.get('lat')
        lng = self.request.query_params.get('lng')
        radius_km = self.request.query_params.get('radius', 15)

        if not lat or not lng:
            raise ValidationError("lat and lng query params are required.")

        lat = float(lat)
        lng = float(lng)
        radius_km = float(radius_km)

        queryset = Profile.objects.exclude(
            latitude__isnull=True
        ).exclude(
            longitude__isnull=True
        ).exclude(
            user=self.request.user
        ).annotate(
            distance_km=ExpressionWrapper(
                6371 * ATan2(
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
        booking = serializer.save(client=self.request.user, provider=gig.provider)

        try:
            provider_profile = Profile.objects.get(user=gig.provider)

            if provider_profile.push_token:
                send_push_notification(
                    push_token=provider_profile.push_token,
                    title='New Booking Request',
                    body=f'{self.request.user.username} wants to book "{gig.title}"',
                    data={'booking_id': booking.id, 'type': 'new_booking'},
                )

            if provider_profile.phone_number:
                send_sms(
                    phone_number=provider_profile.phone_number,
                    message=f'CRAFTD: {self.request.user.username} wants to book "{gig.title}". Open the app to respond.',
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
        provider_id = self.kwargs['pk']
        return Review.objects.filter(reviewee_id=provider_id).order_by('-created_at')


class ProviderDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        provider = get_object_or_404(User, pk=pk)
        profile = get_object_or_404(Profile, user=provider)
        gigs = provider.gigs.filter(is_active=True)
        reviews = Review.objects.filter(reviewee=provider)
        avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0

        data = {
            'id': provider.id,
            'username': provider.username,
            'bio': profile.bio,
            'location': profile.location,
            'city': profile.city,
            'state': profile.state,
            'profile_picture': request.build_absolute_uri(profile.profile_picture.url) if profile.profile_picture else None,
            'is_verified': profile.is_verified,
            'average_rating': round(avg_rating, 1),
            'total_reviews': reviews.count(),
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
        return Conversation.objects.filter(
            Q(client=user) | Q(provider=user)
        ).order_by('-updated_at')  # ← most recent first

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

        message = serializer.save(conversation=conversation, sender=self.request.user)

        conversation.save()

        recipient = conversation.provider if self.request.user == conversation.client else conversation.client

        try:
            recipient_profile = Profile.objects.get(user=recipient)
            if recipient_profile.push_token:
                send_push_notification(
                    push_token=recipient_profile.push_token,
                    title=f'New message from {self.request.user.username}',
                    body=message.content[:100],
                    data={'conversation_id': conversation.id, 'type': 'new_message'},
                )
        except Profile.DoesNotExist:
            pass