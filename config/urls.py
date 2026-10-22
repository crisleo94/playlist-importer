from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.views.generic import RedirectView, TemplateView

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url='/static/favicon.svg', permanent=True)),
    path('admin/', admin.site.urls),
    path('', lambda request: redirect('importer:dashboard'), name='root'),
    path('privacy/', TemplateView.as_view(template_name='legal/privacy.html'), name='privacy'),
    path('terms/', TemplateView.as_view(template_name='legal/terms.html'), name='terms'),
    path('accounts/', include('apps.accounts.urls')),
    path('integrations/', include('apps.integrations.urls')),
    path('dashboard/', include('apps.importer.urls')),
]
