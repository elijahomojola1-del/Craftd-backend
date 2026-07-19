from django.core.mail import send_mail
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

from .models import WaitlistSignup
from .serializers import WaitlistStatusSerializer


def send_otp_email(email, code):
    send_mail(
        subject='Your CRAFTD verification code',
        message=(
            f'Your CRAFTD verification code is: {code}\n\n'
            f'This code expires in 10 minutes. If you did not request this, '
            f'you can safely ignore this email.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )


class SignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        referred_by_code = request.data.get('referral_code', '').strip().upper() or None

        if not email:
            return Response({'detail': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

        signup, created = WaitlistSignup.objects.get_or_create(email=email)

        if signup.verified:
            return Response(
                {'detail': 'This email is already verified on the waitlist.', 'already_verified': True},
                status=status.HTTP_200_OK,
            )

        if not created and not signup.can_resend_otp():
            return Response(
                {'detail': 'Please wait a minute before requesting another code.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        if referred_by_code and not signup.referred_by_code:
            if WaitlistSignup.objects.filter(referral_code=referred_by_code).exclude(email=email).exists():
                signup.referred_by_code = referred_by_code
                signup.save()

        code = signup.issue_new_otp()

        try:
            send_otp_email(email, code)
        except Exception as e:
            return Response(
                {'detail': 'Could not send verification email. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({'detail': 'Verification code sent.'}, status=status.HTTP_200_OK)


class VerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        code = request.data.get('code', '').strip()

        if not email or not code:
            return Response({'detail': 'Email and code are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            signup = WaitlistSignup.objects.get(email=email)
        except WaitlistSignup.DoesNotExist:
            return Response({'detail': 'No signup found for this email.'}, status=status.HTTP_404_NOT_FOUND)

        if signup.verified:
            serializer = WaitlistStatusSerializer(signup)
            return Response(serializer.data, status=status.HTTP_200_OK)

        if not signup.otp_is_valid(code):
            return Response({'detail': 'Invalid or expired code.'}, status=status.HTTP_400_BAD_REQUEST)

        signup.mark_verified()
        serializer = WaitlistStatusSerializer(signup)
        return Response(serializer.data, status=status.HTTP_200_OK)


class StatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        email = request.query_params.get('email', '').strip().lower()
        if not email:
            return Response({'detail': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            signup = WaitlistSignup.objects.get(email=email)
        except WaitlistSignup.DoesNotExist:
            return Response({'detail': 'No signup found for this email.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = WaitlistStatusSerializer(signup)
        return Response(serializer.data, status=status.HTTP_200_OK)