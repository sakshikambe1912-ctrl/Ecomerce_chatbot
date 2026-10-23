from django.urls import path

from assistant.health import HealthAPIView
from assistant.views import ChatAPIView

urlpatterns = [
    path("chat/", ChatAPIView.as_view(), name="chat"),
    path("health/", HealthAPIView.as_view(), name="health"),
]