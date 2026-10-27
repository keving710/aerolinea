from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import (
    AdministradorNuevoForm,
    LoginForm,
    PerfilForm,
    RegistroClienteForm,
    RootCredencialesForm,
)
from .models import Usuario
from .permisos import rol_requerido


def destino_por_rol(usuario):
    if usuario.es_root:
        return reverse("usuarios:administradores")
    if usuario.es_administrador:
        return reverse("vuelos:lista")
    return reverse("inicio")


PASOS_INICIO = [
    ("bi-search", "Busca", "Consulta vuelos nacionales e internacionales con sus horarios y precios."),
    ("bi-ticket-perforated", "Compra o reserva", "Paga con tu tarjeta o reserva tus tiquetes por 24 horas."),
    ("bi-check2-square", "Haz check-in", "Elige tu silla y descarga tu pasabordo antes de viajar."),
]


def inicio(request):
    return render(request, "inicio.html", {"pasos": PASOS_INICIO})


def acceso_restringido(request, exception=None):
    return render(request, "403.html", status=403)


def registro(request):
    if request.user.is_authenticated:
        return redirect(destino_por_rol(request.user))
    form = RegistroClienteForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        login(request, usuario)
        messages.success(request, "¡Registro exitoso! Ya puedes buscar y comprar vuelos.")
        return redirect("inicio")
    return render(request, "usuarios/registro.html", {"form": form})


class IngresarView(LoginView):
    template_name = "usuarios/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return self.get_redirect_url() or destino_por_rol(self.request.user)


@require_POST
def salir(request):
    logout(request)
    messages.info(request, "Cerraste sesión correctamente.")
    return redirect("inicio")


@rol_requerido(Usuario.Rol.CLIENTE, Usuario.Rol.ADMINISTRADOR)
def perfil(request):
    form = PerfilForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Tu perfil se guardó correctamente.")
        return redirect("usuarios:perfil")
    return render(request, "usuarios/perfil.html", {"form": form})


@rol_requerido(Usuario.Rol.ROOT)
def root_credenciales(request):
    form = RootCredencialesForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        update_session_auth_hash(request, usuario)
        messages.success(request, "Credenciales actualizadas.")
        return redirect("usuarios:root_credenciales")
    return render(request, "usuarios/root_credenciales.html", {"form": form})


@rol_requerido(Usuario.Rol.ROOT)
def administradores(request):
    lista = Usuario.objects.filter(rol=Usuario.Rol.ADMINISTRADOR).order_by("username")
    return render(request, "usuarios/administradores.html", {"administradores": lista})


@rol_requerido(Usuario.Rol.ROOT)
def administrador_nuevo(request):
    form = AdministradorNuevoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        admin = form.save()
        messages.success(request, f"Administrador «{admin.username}» creado. Deberá completar su perfil al ingresar.")
        return redirect("usuarios:administradores")
    return render(request, "usuarios/administrador_nuevo.html", {"form": form})
