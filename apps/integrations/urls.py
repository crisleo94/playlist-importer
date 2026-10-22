from django.urls import path
from . import views

app_name = 'integrations'

urlpatterns = [
    path('spotify/connect/', views.spotify_connect, name='spotify_connect'),
    path('spotify/callback/', views.spotify_callback, name='spotify_callback'),
    path('spotify/callback', views.spotify_callback, name='spotify_callback_noslash'),
    path('spotify/disconnect/', views.spotify_disconnect, name='spotify_disconnect'),
    path('youtube/connect/', views.youtube_connect, name='youtube_connect'),
    path('youtube/callback/', views.youtube_callback, name='youtube_callback'),
    path('youtube/callback', views.youtube_callback, name='youtube_callback_noslash'),
    path('youtube/disconnect/', views.youtube_disconnect, name='youtube_disconnect'),
    path('status/', views.connection_status, name='status'),
]
