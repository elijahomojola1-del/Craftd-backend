from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("app/", include("myapp.urls")),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]

# Local development only.
#
# static() returns an empty list whenever DEBUG is False, so appending it
# unconditionally (as before) was already a no-op in production. That is
# precisely why every /media/ URL returned 404 on Railway: Django refuses to
# serve uploaded files in production by design.
#
# In production Cloudinary serves media directly and these routes are not
# involved at all.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)