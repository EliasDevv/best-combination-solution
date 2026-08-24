from django.urls import path

from . import views

urlpatterns = [
    path("teams", views.teams, name="api-teams"),
    path("tournaments", views.tournaments, name="api-tournaments"),
    path("compare", views.compare, name="api-compare"),
    path("searches", views.searches, name="api-searches"),
    path("searches/<uuid:search_id>", views.search_detail, name="api-search-detail"),
]
