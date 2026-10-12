from django.contrib import admin
from .models import Block, Booking, Gig, Profile, PortfolioImage, Report, Review

admin.site.register(Gig)
admin.site.register(Profile)
admin.site.register(PortfolioImage)
admin.site.register(Booking)
admin.site.register(Review)
admin.site.register(Block)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('reported_user', 'reason', 'reporter', 'resolved', 'created_at')
    list_filter = ('resolved', 'reason')
    search_fields = ('reported_user__username', 'reporter__username', 'details')
