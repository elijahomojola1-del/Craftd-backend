from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.SignupView.as_view(), name='waitlist-signup'),
    path('verify/', views.VerifyView.as_view(), name='waitlist-verify'),
    path('status/', views.StatusView.as_view(), name='waitlist-status'),
]