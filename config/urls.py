from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from usuarios import views as usuarios_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", usuarios_views.inicio, name="inicio"),
    path("", include("usuarios.urls")),
    path("vuelos/", include("vuelos.urls")),
]

# Mensaje de "acceso restringido" cuando un rol intenta algo que no le corresponde.
handler403 = "usuarios.views.acceso_restringido"

if settings.DEBUG:
    # Solo desarrollo: sirve las fotos subidas al disco local.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
