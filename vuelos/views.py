from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from usuarios.models import Usuario
from usuarios.permisos import rol_requerido

from .forms import RegresoForm, VueloInternacionalForm, VueloNacionalForm
from .models import Vuelo

SOLO_ADMIN = rol_requerido(Usuario.Rol.ADMINISTRADOR)


@SOLO_ADMIN
def lista(request):
    vuelos = Vuelo.objects.select_related("vuelo_ida")
    return render(request, "vuelos/lista.html", {"vuelos": vuelos})


@SOLO_ADMIN
def nuevo_nacional(request):
    form = VueloNacionalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        vuelo = form.crear(request.user)
        messages.success(request, f"Vuelo {vuelo.codigo} programado.")
        return redirect("vuelos:detalle", codigo=vuelo.codigo)
    return render(request, "vuelos/form_nacional.html", {"form": form})


@SOLO_ADMIN
def nuevo_internacional(request):
    form = VueloInternacionalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ida, regreso = form.crear(request.user)
        texto = f"Vuelo {ida.codigo} programado"
        if regreso:
            texto += f" junto con su regreso {regreso.codigo}"
        messages.success(request, texto + ".")
        return redirect("vuelos:detalle", codigo=ida.codigo)
    return render(request, "vuelos/form_internacional.html", {"form": form})


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
    form = RegresoForm(ida, request.POST or None)
    if request.method == "POST" and form.is_valid():
        regreso = form.crear(request.user)
        messages.success(request, f"Vuelo de regreso {regreso.codigo} programado.")
        return redirect("vuelos:detalle", codigo=regreso.codigo)
    return render(request, "vuelos/form_regreso.html", {"form": form, "ida": ida})
