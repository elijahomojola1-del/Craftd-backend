from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('gigs/', views.GigListCreateView.as_view(), name='gig-list-create'),
    path('gigs/<int:pk>/', views.GigDetailView.as_view(), name='gig-detail'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('save-push-token/', views.SavePushTokenView.as_view(), name='save-push-token'),
    path('portfolio/', views.PortfolioImageListCreateView.as_view(), name='portfolio-list-create'),
    path('portfolio/<int:pk>/', views.PortfolioImageDeleteView.as_view(), name='portfolio-delete'),
    path('bookings/', views.BookingCreateView.as_view(), name='booking-create'),
    path('bookings/mine/', views.MyBookingsView.as_view(), name='my-bookings'),
    path('bookings/received/', views.ReceivedBookingsView.as_view(), name='received-bookings'),
    path('bookings/<int:pk>/', views.BookingDeleteView.as_view(), name='booking-delete'),
    path('bookings/<int:pk>/status/', views.BookingStatusUpdateView.as_view(), name='booking-status-update'),
    path('bookings/<int:pk>/reviews/', views.ReviewCreateView.as_view(), name='review-create'),
    path('users/<int:user_id>/reviews/', views.ProviderReviewListView.as_view(), name='provider-reviews'),
    path('providers/nearby/', views.NearbyProvidersView.as_view(), name='nearby-providers'),
    path('provider/<int:pk>/', views.ProviderDetailView.as_view(), name='provider-detail'),
    path('provider/<int:pk>/reviews/', views.ProviderReviewListView.as_view(), name='provider-reviews-alt'),
    path('reviews/<int:pk>/', views.ReviewDeleteView.as_view(), name='review-delete'),
    path('provider-stats/', views.ProviderStatsView.as_view(), name='provider-stats'),
    path('conversations/', views.ConversationListView.as_view(), name='conversation-list'),
    path('conversations/start/', views.ConversationStartView.as_view(), name='conversation-start'),
    path('conversations/<int:pk>/messages/', views.MessageListCreateView.as_view(), name='conversation-messages'),
]