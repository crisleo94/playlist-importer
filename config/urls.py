from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.views.generic import RedirectView

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url='/static/favicon.svg', permanent=True)),
    path('admin/', admin.site.urls),
    path('', lambda request: redirect('importer:dashboard'), name='root'),
    path('accounts/', include('apps.accounts.urls')),
    path('integrations/', include('apps.integrations.urls')),
    path('dashboard/', include('apps.importer.urls')),
]
