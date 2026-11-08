from django.urls import path

from input_guard import views

app_name = "input_guard"

urlpatterns = [
    path("", views.playground, name="playground"),
    path("how-it-works", views.how_it_works, name="how-it-works"),
    path("api/v1/validate-query", views.validate_query, name="validate-query"),
    path("health/live", views.health_live, name="health-live"),
    path("health/ready", views.health_ready, name="health-ready"),
]
