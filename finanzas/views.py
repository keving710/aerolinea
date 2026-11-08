from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.utils.formats import number_format
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from usuarios.models import Usuario
from usuarios.permisos import rol_requerido
from . import services
from .forms import OperacionForm, TarjetaForm
from .models import Movimiento, Tarjeta

SOLO_CLIENTE = rol_requerido(Usuario.Rol.CLIENTE)


@never_cache
@SOLO_CLIENTE
@require_http_methods(["GET"])
def panel(request):
    tarjetas = Tarjeta.objects.filter(cliente=request.user)
    movimientos = Movimiento.objects.filter(tarjeta__cliente=request.user).select_related("tarjeta")
    return render(request, "finanzas/panel.html", {
        "tarjetas": tarjetas, "saldo_total": tarjetas.aggregate(total=Sum("saldo"))["total"] or 0,
        "page_obj": Paginator(movimientos, 15).get_page(request.GET.get("page")),
    })


@sensitive_post_parameters("numero")
@never_cache
@SOLO_CLIENTE
@require_http_methods(["GET", "POST"])
def nueva_tarjeta(request):
    form = TarjetaForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            services.registrar_tarjeta(request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Tarjeta registrada correctamente.")
            return redirect("finanzas:panel")
    return render(request, "finanzas/operacion.html", {
        "form": form, "titulo": "Registrar tarjeta", "boton": "Guardar tarjeta ficticia",
    })


@never_cache
@SOLO_CLIENTE
@require_http_methods(["GET", "POST"])
def operacion(request, pago=False):
    form = OperacionForm(request.user, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            movimiento = (services.cobrar if pago else services.recargar)(
                request.user, d["tarjeta"].pk, d["valor"], d["referencia"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"{'Pago simulado' if pago else 'Recarga'} registrado. "
                             f"Saldo resultante de la operación: COP {number_format(movimiento.saldo_resultante, 2, force_grouping=True)}.")
            return redirect("finanzas:panel")
    return render(request, "finanzas/operacion.html", {
        "form": form, "titulo": "Simular pago" if pago else "Recargar saldo",
        "boton": "Confirmar pago simulado" if pago else "Confirmar recarga",
        "sin_tarjetas": not form.fields["tarjeta"].queryset.exists(), "pago": pago,
    })
