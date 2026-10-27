from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def rol_requerido(*roles):
    """Restringe una vista a ciertos roles (HU 3).

    - Visitante (sin sesión): se envía a iniciar sesión.
    - Usuario con otro rol: página de acceso restringido (403).
    """

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.info(request, "Inicia sesión para acceder a esta sección.")
                from django.urls import reverse
                from urllib.parse import urlencode

                return redirect(
                    f"{reverse('usuarios:login')}?{urlencode({'next': request.get_full_path()})}"
                )
            if request.user.rol not in roles:
                raise PermissionDenied
            return vista(request, *args, **kwargs)

        return envoltura

    return decorador
