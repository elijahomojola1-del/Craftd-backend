from django.contrib import admin
from .models import (
    AppSettings, Block, Booking, Gig, Profile, PortfolioImage, Report, Review,
    SubscriptionRequest,
)

admin.site.register(Gig)
admin.site.register(PortfolioImage)
admin.site.register(Booking)
admin.site.register(Review)
admin.site.register(Block)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    # Tick "is subscribed" here to switch a subscription on or off.
    list_display = ('user', 'display_name', 'role', 'is_subscribed', 'subscription_expires', 'is_verified')
    list_filter = ('is_subscribed', 'role', 'is_verified')
    list_editable = ('is_subscribed', 'is_verified')
    search_fields = ('user__username', 'user__email', 'display_name')


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('reported_user', 'reason', 'reporter', 'resolved', 'created_at')
    list_filter = ('resolved', 'reason')
    search_fields = ('reported_user__username', 'reporter__username', 'details')


@admin.register(SubscriptionRequest)
class SubscriptionRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'handled', 'created_at')
    list_filter = ('handled',)
    list_editable = ('handled',)
    search_fields = ('user__username', 'user__email')


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'free_provider_bookings', 'free_client_bookings', 'subscription_price_text')

    def has_add_permission(self, request):
        # There is only ever one row of settings.
        return not AppSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
