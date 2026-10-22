from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from apps.integrations.models import PlatformToken


@login_required
def dashboard_view(request):
    tokens = {
        token.platform: token
        for token in PlatformToken.objects.filter(user=request.user)
    }

    context = {
        'spotify_token': tokens.get(PlatformToken.PLATFORM_SPOTIFY),
        'youtube_token': tokens.get(PlatformToken.PLATFORM_YOUTUBE),
    }
    return render(request, 'importer/dashboard.html', context)
