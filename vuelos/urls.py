from django.urls import path

from . import views

app_name = "vuelos"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nacional/nuevo/", views.nuevo_nacional, name="nuevo_nacional"),
    path("internacional/nuevo/", views.nuevo_internacional, name="nuevo_internacional"),
    path("<str:codigo>/", views.detalle, name="detalle"),
    path("<str:codigo>/regreso/", views.agregar_regreso, name="regreso"),
]
