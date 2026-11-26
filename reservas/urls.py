from django.urls import path

from . import views

app_name = "reservas"
urlpatterns = [
    path("", views.historial, name="historial"),
    path("carrito/", views.ver_carrito, name="carrito"),
    path("carrito/quitar/<int:indice>/", views.quitar_del_carrito, name="quitar"),
    path("vuelo/<str:codigo>/<str:accion>/", views.iniciar, name="iniciar"),
    path("<str:codigo>/", views.detalle, name="detalle"),
    path("<str:codigo>/cancelar/", views.cancelar, name="cancelar"),
    path("<str:codigo>/pagar/", views.pagar, name="pagar"),
]
