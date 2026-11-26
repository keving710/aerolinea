from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.formats import number_format
from django.views.decorators.http import require_http_methods

from reservas import servicios
from reservas.models import Reserva, Tiquete

from .iteracion3_forms import CancelarVueloForm, PromocionForm
from .models import Vuelo
from .views import SOLO_ADMIN


@SOLO_ADMIN
@require_http_methods(["GET", "POST"])
def promocion(request, codigo):
    """Aplica una promoción solo a los cupos disponibles; los tiquetes ya emitidos conservan su valor (HU 16)."""
    servicios.marcar_realizados()
    vuelo = get_object_or_404(Vuelo, codigo=codigo)
    form = PromocionForm(request.POST or None, initial={"descuento": vuelo.descuento_porcentaje})
    motivo = vuelo.motivo_no_modificable
    if motivo:
        return render(request, "vuelos/promocion.html", {"vuelo": vuelo, "motivo": motivo}, status=409)
    if request.method == "POST" and form.is_valid():
        descuento = form.cleaned_data["descuento"]
        with transaction.atomic():
            vuelo = Vuelo.objects.select_for_update().get(pk=vuelo.pk)
            servicios.liberar_vencidas(vuelo_ids=[vuelo.pk])
            vuelo.refresh_from_db()
            if vuelo.motivo_no_modificable:
                form.add_error(None, vuelo.motivo_no_modificable)
            elif descuento > 0 and vuelo.cupos_disponibles == 0:
                form.add_error(None, "El vuelo no tiene cupos disponibles: no hay a quién aplicarle la promoción.")
            else:
                vuelo.descuento_porcentaje = descuento
                vuelo.save(update_fields=["descuento_porcentaje"])
                messages.success(request, (f"Promoción de {descuento.normalize():f}% aplicada a {vuelo.cupos_disponibles} cupos disponibles. "
                                           f"Nuevo valor: COP {number_format(vuelo.costo_vigente, 0, force_grouping=True)} por persona.")
                                 if descuento > 0 else "Promoción retirada: el valor por persona volvió a su costo base.")
                return redirect("vuelos:detalle", codigo=vuelo.codigo)
    return render(request, "vuelos/promocion.html", {"vuelo": vuelo, "form": form,
                                                      "vendidos": vuelo.tiquetes_vendidos, "reservados": vuelo.cupos_reservados})


@SOLO_ADMIN
@require_http_methods(["GET", "POST"])
def cancelar(request, codigo):
    """Cancela el vuelo reubicando o reintegrando a cada pasajero afectado (HU 17)."""
    servicios.marcar_realizados()
    servicios.liberar_vencidas()
    vuelo = get_object_or_404(Vuelo, codigo=codigo)
    motivo = vuelo.motivo_no_modificable
    if motivo:
        return render(request, "vuelos/cancelar.html", {"vuelo": vuelo, "motivo": motivo}, status=409)
    form = CancelarVueloForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            r = servicios.cancelar_vuelo(request.user, vuelo.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            partes = [f"{r['reubicados']} tiquete(s) reubicado(s) en otro vuelo",
                      f"{r['reintegrados']} reintegrado(s) por COP {number_format(r['valor_reintegrado'], 0, force_grouping=True)}",
                      f"{r['liberados']} reserva(s) sin pago liberada(s)"]
            messages.success(request, f"Vuelo {vuelo.codigo} cancelado: " + ", ".join(partes) + ".")
            return redirect("vuelos:detalle", codigo=vuelo.codigo)
    activos = Tiquete.objects.filter(vuelo=vuelo, estado=Tiquete.Estado.ACTIVO)
    return render(request, "vuelos/cancelar.html", {
        "vuelo": vuelo, "form": form,
        "comprados": activos.filter(reserva__estado=Reserva.Estado.COMPRADA).count(),
        "reservados": activos.filter(reserva__estado=Reserva.Estado.RESERVADA).count(),
        "alternativas": servicios.alternativas_para(vuelo)[:5],
    })
