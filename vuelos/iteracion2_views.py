from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .catalogo import buscar, disponibles
from .iteracion2_forms import BusquedaForm, formulario_edicion, validar_vinculos
from .models import Vuelo
from .views import SOLO_ADMIN


@require_http_methods(["GET"])
def busqueda(request):
    form = BusquedaForm(request.GET)
    vuelos = buscar(form.cleaned_data) if form.is_valid() else Vuelo.objects.none()
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "vuelos/busqueda.html", {
        "form": form, "page_obj": Paginator(vuelos, 9).get_page(request.GET.get("page")),
        "parametros": parametros.urlencode(),
    })


@require_http_methods(["GET"])
def publico(request, codigo):
    return render(request, "vuelos/publico.html", {"vuelo": get_object_or_404(disponibles(), codigo=codigo)})


@SOLO_ADMIN
@require_http_methods(["GET", "POST"])
@transaction.atomic
def editar(request, codigo):
    # Bloquear todos los tramos vinculados en orden fijo evita carreras entre editores.
    original = get_object_or_404(Vuelo, codigo=codigo)
    raiz = original.vuelo_ida_id or original.pk
    from django.db.models import Q
    bloqueados = list(Vuelo.objects.select_for_update().filter(Q(pk=raiz) | Q(vuelo_ida_id=raiz)).order_by("pk"))
    vuelo = next(v for v in bloqueados if v.pk == original.pk)
    motivo = vuelo.motivo_no_editable
    form = formulario_edicion(vuelo, request.POST if request.method == "POST" else None)
    if motivo:
        return render(request, "vuelos/editar.html", {"vuelo": vuelo, "motivo": motivo}, status=409)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        vuelo.origen, vuelo.destino = d["origen"], d["destino"]
        vuelo.costo_persona = d["costo_persona"]
        nacional = vuelo.tipo == Vuelo.Tipo.NACIONAL
        vuelo.salida = d["_salida_utc" if nacional else "_salida"]
        vuelo.llegada = d["_llegada_utc" if nacional else "_llegada"]
        vuelo.duracion_minutos = d["_minutos"]
        try:
            validar_vinculos(vuelo)
            vuelo.full_clean()
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            vuelo.save(update_fields=["origen", "destino", "costo_persona", "salida", "llegada", "duracion_minutos"])
            messages.success(request, f"Vuelo {vuelo.codigo} actualizado correctamente.")
            return redirect("vuelos:detalle", codigo=vuelo.codigo)
    return render(request, "vuelos/editar.html", {"vuelo": vuelo, "form": form})
