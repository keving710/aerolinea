from datetime import date, datetime, time

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from usuarios.models import Usuario
from usuarios.permisos import rol_requerido

from . import reglas
from .forms import RegresoForm, VueloInternacionalForm, VueloNacionalForm
from .models import Consecutivo, Vuelo

SOLO_ADMIN = rol_requerido(Usuario.Rol.ADMINISTRADOR)


def contexto_formulario(**extra):
    """Datos comunes de los formularios de vuelo (código siguiente y duraciones estimadas)."""
    return {"codigo": Consecutivo.proximo_codigo(), "duraciones": reglas.duraciones_para_js(), **extra}


ESTADOS_LISTA = {"programado": "Vuelos programados", "realizado": "Vuelos realizados", "cancelado": "Vuelos cancelados"}


@SOLO_ADMIN
def lista(request, estado="programado"):
    """Programados, realizados (HU 18) y cancelados (HU 17), cada uno en su categoría."""
    from reservas import servicios
    servicios.mantenimiento()
    vuelos = Vuelo.objects.select_related("vuelo_ida").filter(estado=estado)
    if estado == Vuelo.Estado.REALIZADO:
        vuelos = vuelos.order_by("-salida")
    return render(request, "vuelos/lista.html", {"vuelos": vuelos, "estado": estado, "titulo": ESTADOS_LISTA[estado]})


@SOLO_ADMIN
def nuevo_nacional(request):
    form = VueloNacionalForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        vuelo = form.crear(request.user)
        messages.success(request, f"Vuelo {vuelo.codigo} programado.")
        return redirect("vuelos:detalle", codigo=vuelo.codigo)
    return render(request, "vuelos/form_nacional.html", contexto_formulario(form=form))


@SOLO_ADMIN
def nuevo_internacional(request):
    form = VueloInternacionalForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        ida, regreso = form.crear(request.user)
        texto = f"Vuelo {ida.codigo} programado"
        if regreso:
            texto += f" junto con su regreso {regreso.codigo}"
        messages.success(request, texto + ".")
        return redirect("vuelos:detalle", codigo=ida.codigo)
    return render(request, "vuelos/form_internacional.html", contexto_formulario(form=form))


@SOLO_ADMIN
def detalle(request, codigo):
    vuelo = get_object_or_404(Vuelo, codigo=codigo)
    return render(request, "vuelos/detalle.html", {"vuelo": vuelo})


@SOLO_ADMIN
def agregar_regreso(request, codigo):
    ida = get_object_or_404(Vuelo, codigo=codigo, tipo=Vuelo.Tipo.INTERNACIONAL, vuelo_ida__isnull=True)
    if hasattr(ida, "vuelo_regreso"):
        messages.info(request, "Este vuelo ya tiene un regreso programado.")
        return redirect("vuelos:detalle", codigo=ida.codigo)
    form = RegresoForm(ida, request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        regreso = form.crear(request.user)
        messages.success(request, f"Vuelo de regreso {regreso.codigo} programado.")
        return redirect("vuelos:detalle", codigo=regreso.codigo)
    return render(request, "vuelos/form_regreso.html", contexto_formulario(form=form, ida=ida))


def _error(mensaje):
    return JsonResponse({"error": mensaje}, status=400)


@SOLO_ADMIN
@require_GET
def calcular(request):
    """Calcula en vivo la duración y la hora de llegada mientras el administrador llena el formulario.

    Usa exactamente las mismas reglas que se aplican al guardar el vuelo.
    """
    g = request.GET
    try:
        salida = datetime.combine(date.fromisoformat(g.get("fecha", "")), time.fromisoformat(g.get("hora_salida", "")))
    except ValueError:
        return _error("Completa la fecha y la hora de salida.")

    if g.get("tipo") == Vuelo.Tipo.NACIONAL:
        try:
            llegada_hora = time.fromisoformat(g.get("hora_llegada", ""))
        except ValueError:
            return _error("Completa la hora de llegada.")
        try:
            minutos, llegada = reglas.duracion_nacional(salida, llegada_hora)
        except ValueError as exc:
            return _error(str(exc))
        llegada_texto = llegada.strftime("%d/%m/%Y %H:%M")
    else:
        origen, destino = g.get("origen", ""), g.get("destino", "")
        colombianas, exteriores = set(reglas.ORIGENES_INTERNACIONALES), set(reglas.DESTINOS_INTERNACIONALES)
        if not ({origen, destino} & colombianas and {origen, destino} & exteriores):
            return _error("Elige el origen y el destino.")
        horas, mins = g.get("horas", "").strip(), g.get("minutos", "").strip()
        if not horas and not mins:
            minutos = reglas.duracion_estimada(origen, destino)
        else:
            try:
                minutos = int(horas or 0) * 60 + int(mins or 0)
            except ValueError:
                return _error("La duración debe estar en números.")
        if not minutos or minutos <= 0:
            return _error("La duración debe ser mayor a cero.")
        _, llegada_utc = reglas.calcular_llegada_internacional(salida, reglas.zona_de(origen), destino, minutos)
        llegada_texto = reglas.formatear(llegada_utc, reglas.zona_de(destino))

    return JsonResponse({"minutos": minutos, "duracion": reglas.formatear_duracion(minutos), "llegada": llegada_texto})
