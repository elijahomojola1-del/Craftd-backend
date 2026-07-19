from django.contrib import admin
from .models import Booking, Gig, Profile, PortfolioImage

admin.site.register(Gig)
admin.site.register(Profile)
admin.site.register(PortfolioImage)
admin.site.register(Booking)