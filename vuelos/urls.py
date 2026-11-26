from django.urls import path

from . import views, iteracion2_views as v2, iteracion3_views as v3

app_name = "vuelos"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("realizados/", views.lista, {"estado": "realizado"}, name="realizados"),
    path("cancelados/", views.lista, {"estado": "cancelado"}, name="cancelados"),
    path("nacional/nuevo/", views.nuevo_nacional, name="nuevo_nacional"),
    path("internacional/nuevo/", views.nuevo_internacional, name="nuevo_internacional"),
    path("buscar/", v2.busqueda, name="busqueda"),
    path("calcular/", views.calcular, name="calcular"),
    path("publicados/<str:codigo>/", v2.publico, name="publico"),
    path("<str:codigo>/editar/", v2.editar, name="editar"),
    path("<str:codigo>/promocion/", v3.promocion, name="promocion"),
    path("<str:codigo>/cancelar/", v3.cancelar, name="cancelar"),
    path("<str:codigo>/", views.detalle, name="detalle"),
    path("<str:codigo>/regreso/", views.agregar_regreso, name="regreso"),
]
