from django.urls import path

from . import views, iteracion2_views as v2

app_name = "vuelos"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nacional/nuevo/", views.nuevo_nacional, name="nuevo_nacional"),
    path("internacional/nuevo/", views.nuevo_internacional, name="nuevo_internacional"),
    path("buscar/", v2.busqueda, name="busqueda"),
    path("publicados/<str:codigo>/", v2.publico, name="publico"),
    path("<str:codigo>/editar/", v2.editar, name="editar"),
    path("<str:codigo>/", views.detalle, name="detalle"),
    path("<str:codigo>/regreso/", views.agregar_regreso, name="regreso"),
]
