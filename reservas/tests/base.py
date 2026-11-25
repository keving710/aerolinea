from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from finanzas import services as finanzas
from usuarios.models import Usuario
from vuelos import reglas
from vuelos.models import Vuelo


def viajero(documento="1000001", nombres="Ana", apellidos="Pérez", nacimiento="1990-05-01", clase="economica", **extra):
    datos = {"documento": documento, "nombres": nombres, "apellidos": apellidos, "fecha_nacimiento": nacimiento,
             "genero": "femenino", "telefono": "3001234567", "correo": f"v{documento}@correo.com",
             "contacto_nombre": "Luis Pérez", "contacto_telefono": "3109876543", "clase": clase}
    datos.update(extra)
    return datos


def datos_post(viajeros, trayecto="unico", regreso=""):
    data = {"trayecto": trayecto, "regreso": regreso, "viajero-TOTAL_FORMS": len(viajeros), "viajero-INITIAL_FORMS": 0,
            "viajero-MIN_NUM_FORMS": 1, "viajero-MAX_NUM_FORMS": 5}
    for i, v in enumerate(viajeros):
        for campo, valor in v.items():
            data[f"viajero-{i}-{campo}"] = valor
    return data


class BaseReservas(TestCase):
    NUMERO = "4111111111111111"

    def setUp(self):
        self.admin = Usuario.objects.create_user("admin3", password="x", rol="administrador")
        self.cliente = Usuario.objects.create_user("cliente3", password="x", rol="cliente", email="c3@correo.com")
        self.otro = Usuario.objects.create_user("otro3", password="x", rol="cliente", email="o3@correo.com")
        self.root = Usuario.objects.create_user("root3", password="x", rol="root")
        self.tarjeta = self.tarjeta_con_saldo(self.cliente, 5_000_000)
        self.vuelo = self.crear_vuelo()

    def tarjeta_con_saldo(self, cliente, saldo, numero=None):
        return finanzas.registrar_tarjeta(cliente, numero or self.NUMERO, "debito", saldo,
                                          mes=12, anio=timezone.localdate().year + 3, cvv="123")

    def crear_vuelo(self, dias=10, origen="Pereira", destino="Bogotá", costo="200000", tipo="nacional", horas=0, **extra):
        salida = timezone.now() + timedelta(days=dias, hours=horas)
        capacidad = reglas.CAPACIDAD_NACIONAL if tipo == "nacional" else reglas.CAPACIDAD_INTERNACIONAL
        return Vuelo.objects.create(tipo=tipo, origen=origen, destino=destino, salida=salida,
                                    llegada=salida + timedelta(hours=1), duracion_minutos=60,
                                    costo_persona=Decimal(costo), capacidad=capacidad, creado_por=self.admin, **extra)

    def saldo(self, tarjeta=None):
        t = tarjeta or self.tarjeta
        t.refresh_from_db()
        return t.saldo
