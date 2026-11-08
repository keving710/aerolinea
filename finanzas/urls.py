from django.urls import path
from . import views

app_name = "finanzas"
urlpatterns = [
    path("", views.panel, name="panel"),
    path("tarjetas/nueva/", views.nueva_tarjeta, name="nueva_tarjeta"),
    path("recargar/", views.operacion, name="recargar"),
    path("simular-pago/", views.operacion, {"pago": True}, name="simular_pago"),
]
