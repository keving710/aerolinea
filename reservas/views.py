from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.formats import number_format
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from usuarios.models import Usuario
from usuarios.permisos import rol_requerido
from vuelos.catalogo import disponibles

from . import carrito, servicios
from .forms import PagoForm, TrayectoForm, ViajerosFormSet
from .models import Reserva

SOLO_CLIENTE = rol_requerido(Usuario.Rol.CLIENTE)


def _cop(valor):
    return number_format(valor, 0, force_grouping=True)


def cliente_para_comprar(vista):
    """El visitante debe registrarse (HU 26); root y administrador no pueden comprar (403)."""
    def envoltura(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.info(request, "Para comprar o reservar debes registrarte o iniciar sesión como cliente.")
            from urllib.parse import urlencode
            from django.urls import reverse
            return redirect(f"{reverse('usuarios:registro')}?{urlencode({'next': request.get_full_path()})}")
        if not request.user.es_cliente:
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    envoltura.__name__ = vista.__name__
    return envoltura


def _linea(vuelo, trayecto, viajeros):
    return {"vuelo": vuelo.codigo, "regreso": trayecto.get("regreso") or "", "viajeros": viajeros}


@sensitive_post_parameters()
@never_cache
@cliente_para_comprar
@require_http_methods(["GET", "POST"])
def iniciar(request, codigo, accion):
    """Datos de los viajeros y clase para comprar (carrito) o reservar un vuelo (HU 26, 27, 28, 30)."""
    if accion not in ("comprar", "reservar"):
        raise PermissionDenied
    servicios.liberar_vencidas()
    vuelo = get_object_or_404(disponibles(), codigo=codigo)
    data = request.POST if request.method == "POST" else None
    solicitados = request.GET.get("viajeros", "1")
    inicial = min(max(int(solicitados), 1), servicios.LIMITE_POR_VUELO) if solicitados.isdigit() else 1
    trayecto = TrayectoForm(vuelo, data)
    formset = ViajerosFormSet(data, initial=None if data is not None else [{}] * inicial, prefix="viajero")
    formset.fecha_viaje = timezone.localtime(vuelo.salida, vuelo.zona_origen).date()
    errores = []
    if request.method == "POST" and trayecto.is_valid() and formset.is_valid():
        viajeros = [dict(f.cleaned_data) for f in formset.forms]
        linea = _linea(vuelo, trayecto.cleaned_data, viajeros)
        try:
            if accion == "reservar":
                reserva = servicios.reservar(request.user, linea)
            else:
                servicios.validar_linea(request.user, linea, carrito.obtener(request))
        except ValidationError as exc:
            errores = exc.messages
        else:
            if accion == "reservar":
                messages.success(request, f"Reserva {reserva.codigo} creada. Tus cupos se retienen hasta {timezone.localtime(reserva.expira_en):%d/%m/%Y %H:%M}.")
                return redirect("reservas:detalle", codigo=reserva.codigo)
            carrito.agregar(request, linea)
            messages.success(request, "Tiquetes agregados al carrito. Revisa el detalle y elige tu tarjeta para pagar.")
            return redirect("reservas:carrito")
    elif request.method == "POST":
        errores = [e for e in formset.non_form_errors()]
    return render(request, "reservas/iniciar.html", {
        "vuelo": vuelo, "accion": accion, "trayecto": trayecto, "formset": formset, "errores": errores,
        "maximo": servicios.LIMITE_POR_VUELO,
        "clases": {"primera": vuelo.rango_clase("primera"), "economica": vuelo.rango_clase("economica")},
    })


@sensitive_post_parameters()
@never_cache
@SOLO_CLIENTE
@require_http_methods(["GET", "POST"])
def ver_carrito(request):
    servicios.liberar_vencidas()
    lineas, invalidas, total = [], [], 0
    for i, linea in enumerate(carrito.obtener(request)):
        try:
            tramos = servicios.tramos_de_linea(linea)
            valor = servicios.total_linea(linea)
        except ValidationError as exc:
            invalidas.append((i, exc.messages[0]))
            continue
        lineas.append({"indice": i, "tramos": [(v, tramo) for v, tramo, _ in tramos], "viajeros": tramos[0][2], "total": valor})
        total += valor
    form = PagoForm(request.user, request.POST if request.method == "POST" else None, initial={"total": total})
    if request.method == "POST" and form.is_valid():
        if invalidas:
            messages.error(request, "Quita del carrito los vuelos que ya no están disponibles antes de pagar.")
        elif form.cleaned_data["total"] != total:
            messages.warning(request, "El valor de tu carrito cambió (por ejemplo, por una promoción). Revísalo y confirma de nuevo.")
        elif form.cleaned_data["tarjeta"].saldo < total:
            form.add_error("tarjeta", "No tienes saldo disponible suficiente en esta tarjeta. Recárgala o elige otra.")
        else:
            try:
                reservas = servicios.comprar(request.user, carrito.obtener(request), form.cleaned_data["tarjeta"])
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                carrito.vaciar(request)
                messages.success(request, f"Compra confirmada por COP {_cop(total)}. Enviamos el código de reserva a cada viajero.")
                if len(reservas) == 1:
                    return redirect("reservas:detalle", codigo=reservas[0].codigo)
                return redirect("reservas:historial")
    return render(request, "reservas/carrito.html", {
        "lineas": lineas, "invalidas": invalidas, "total": total, "form": form,
        "sin_tarjetas": not form.fields["tarjeta"].queryset.exists(),
    })


@SOLO_CLIENTE
@require_POST
def quitar_del_carrito(request, indice):
    carrito.quitar(request, indice)
    messages.info(request, "Quitamos el elemento de tu carrito.")
    return redirect("reservas:carrito")


@never_cache
@SOLO_CLIENTE
@require_http_methods(["GET"])
def historial(request):
    """Todas las compras y reservas del cliente con su estado y el de su check-in (HU 33)."""
    servicios.liberar_vencidas()
    reservas = (Reserva.objects.filter(cliente=request.user)
                .prefetch_related("tiquetes__vuelo").select_related("tarjeta"))
    estado = request.GET.get("estado", "")
    if estado in Reserva.Estado.values:
        reservas = reservas.filter(estado=estado)
    return render(request, "reservas/historial.html", {
        "page_obj": Paginator(reservas, 10).get_page(request.GET.get("page")),
        "estado": estado, "estados": Reserva.Estado.choices, "parametros": f"estado={estado}" if estado else "",
    })


@never_cache
@SOLO_CLIENTE
@require_http_methods(["GET"])
def detalle(request, codigo):
    servicios.liberar_vencidas()
    reserva = get_object_or_404(Reserva.objects.prefetch_related("tiquetes__vuelo"), codigo=codigo, cliente=request.user)
    return render(request, "reservas/detalle.html", _contexto_detalle(request, reserva))


def _contexto_detalle(request, reserva, form_pago=None):
    activos = reserva.tiquetes_activos
    return {
        "reserva": reserva, "tiquetes": list(reserva.tiquetes.all()), "total": reserva.total_activo,
        "motivo_no_cancelable": servicios.motivo_no_cancelable(reserva) if reserva.activa else "",
        "form_pago": form_pago or (PagoForm(request.user, initial={"total": reserva.total_activo})
                                    if reserva.estado == Reserva.Estado.RESERVADA else None),
        "hay_activos": bool(activos),
    }


@never_cache
@SOLO_CLIENTE
@require_POST
def cancelar(request, codigo):
    reserva = get_object_or_404(Reserva, codigo=codigo, cliente=request.user)
    try:
        reserva, reintegro = servicios.cancelar(request.user, reserva.pk)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        texto = f"{reserva.codigo} cancelada. Liberamos tus cupos."
        if reintegro:
            texto += f" Reintegramos COP {_cop(reintegro)} a tu tarjeta y quedó en tu historial de movimientos."
        messages.success(request, texto)
    return redirect("reservas:detalle", codigo=codigo)


@never_cache
@SOLO_CLIENTE
@require_POST
def pagar(request, codigo):
    reserva = get_object_or_404(Reserva.objects.prefetch_related("tiquetes__vuelo"), codigo=codigo, cliente=request.user)
    form = PagoForm(request.user, request.POST)
    if form.is_valid():
        if form.cleaned_data["total"] != reserva.total_activo:
            messages.warning(request, "El valor de la reserva cambió. Revísalo y confirma de nuevo.")
        elif form.cleaned_data["tarjeta"].saldo < reserva.total_activo:
            form.add_error("tarjeta", "No tienes saldo disponible suficiente en esta tarjeta. Recárgala o elige otra.")
        else:
            try:
                servicios.pagar_reserva(request.user, reserva.pk, form.cleaned_data["tarjeta"])
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, f"Pago confirmado: la reserva {reserva.codigo} ahora es una compra.")
                return redirect("reservas:detalle", codigo=codigo)
    reserva.refresh_from_db()
    return render(request, "reservas/detalle.html", _contexto_detalle(request, reserva, form), status=200 if not form.errors else 400)
