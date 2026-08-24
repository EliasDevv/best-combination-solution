from django.contrib import admin

from .models import Game, SavedSearch, StreamingOffer, StreamingPackage


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("id", "team_home", "team_away", "starts_at", "tournament_name")
    list_filter = ("tournament_name",)
    search_fields = ("team_home", "team_away")


@admin.register(StreamingPackage)
class StreamingPackageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "monthly_price_cents",
        "monthly_price_yearly_subscription_in_cents",
    )


@admin.register(StreamingOffer)
class StreamingOfferAdmin(admin.ModelAdmin):
    list_display = ("id", "game", "streaming_package", "live", "highlights")
    list_filter = ("live", "highlights", "streaming_package")


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at")
    readonly_fields = ("id", "created_at", "params", "result_summary")
