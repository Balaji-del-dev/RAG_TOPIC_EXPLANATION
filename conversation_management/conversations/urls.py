from django.urls import include, path
from rest_framework.routers import DefaultRouter

from conversations import views

router = DefaultRouter()
router.register("conversations", views.ConversationViewSet, basename="conversation")

urlpatterns = [
    path("", include(router.urls)),
    path("chat/", views.ChatView.as_view(), name="chat"),
    path("session/", views.SessionView.as_view(), name="session"),
]
