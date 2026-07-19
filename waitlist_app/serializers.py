from rest_framework import serializers
from .models import WaitlistSignup


class WaitlistStatusSerializer(serializers.ModelSerializer):
    referral_count = serializers.ReadOnlyField()

    class Meta:
        model = WaitlistSignup
        fields = [
            'email', 'verified', 'position', 'referral_code',
            'referral_count', 'created_at',
        ]