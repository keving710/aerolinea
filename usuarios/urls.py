from django.urls import path

from . import views

app_name = "usuarios"

urlpatterns = [
    path("registro/", views.registro, name="registro"),
    path("ingresar/", views.IngresarView.as_view(), name="login"),
    path("salir/", views.salir, name="logout"),
    path("perfil/", views.perfil, name="perfil"),
    path("root/credenciales/", views.root_credenciales, name="root_credenciales"),
    path("root/administradores/", views.administradores, name="administradores"),
    path("root/administradores/nuevo/", views.administrador_nuevo, name="administrador_nuevo"),
]
