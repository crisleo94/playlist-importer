from django.urls import path
from . import views

app_name = 'importer'

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('spotify/playlists/', views.spotify_playlists_view, name='spotify_playlists'),
    path('youtube/playlists/', views.youtube_playlists_view, name='youtube_playlists'),
    path('tracks/<str:platform>/<str:playlist_id>/', views.playlist_tracks_modal_view, name='playlist_tracks_modal'),
]
