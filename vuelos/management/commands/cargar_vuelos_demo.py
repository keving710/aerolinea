"""Carga vuelos simulados (nacionales e internacionales con regreso) en fechas futuras.

Uso:
    python manage.py cargar_vuelos_demo               # 40 nacionales + 12 internacionales, próximos 30 días
    python manage.py cargar_vuelos_demo --dias 60 --nacionales 80 --internacionales 20
    python manage.py cargar_vuelos_demo --limpiar     # borra antes los vuelos simulados futuros sin ventas
"""
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from usuarios.models import Usuario
from vuelos import reglas
from vuelos.models import Vuelo

# (origen, destino, duración en minutos, precio base COP)
RUTAS_NACIONALES = [
    ("Bogotá", "Medellín", 55, 220_000), ("Bogotá", "Cali", 65, 240_000),
    ("Bogotá", "Cartagena de Indias", 90, 310_000), ("Bogotá", "Barranquilla", 95, 290_000),
    ("Bogotá", "Santa Marta", 95, 300_000), ("Bogotá", "Bucaramanga", 60, 210_000),
    ("Bogotá", "Pereira", 50, 190_000), ("Bogotá", "San Andrés", 135, 420_000),
    ("Bogotá", "Leticia", 120, 450_000), ("Bogotá", "Cúcuta", 70, 230_000),
    ("Bogotá", "Pasto", 85, 260_000), ("Bogotá", "Montería", 80, 250_000),
    ("Medellín", "Bogotá", 55, 220_000), ("Medellín", "Cartagena de Indias", 75, 260_000),
    ("Medellín", "Cali", 55, 200_000), ("Medellín", "San Andrés", 110, 390_000),
    ("Medellín", "Santa Marta", 80, 270_000), ("Cali", "Bogotá", 65, 240_000),
    ("Cali", "Cartagena de Indias", 95, 300_000), ("Cali", "Medellín", 55, 200_000),
    ("Pereira", "Bogotá", 50, 190_000), ("Pereira", "Cartagena de Indias", 85, 280_000),
    ("Barranquilla", "Bogotá", 95, 290_000), ("Cartagena de Indias", "Bogotá", 90, 310_000),
    ("Cartagena de Indias", "Medellín", 75, 260_000), ("Bucaramanga", "Bogotá", 60, 210_000),
    ("Santa Marta", "Bogotá", 95, 300_000), ("San Andrés", "Bogotá", 135, 420_000),
]

# (origen, destino, duración en minutos, precio base COP)
RUTAS_INTERNACIONALES = [
    ("Bogotá", "Madrid", 615, 3_200_000), ("Bogotá", "Londres", 640, 3_500_000),
    ("Bogotá", "New York", 345, 1_900_000), ("Bogotá", "Miami", 225, 1_250_000),
    ("Bogotá", "Buenos Aires", 395, 2_100_000), ("Medellín", "Madrid", 600, 3_100_000),
    ("Medellín", "Miami", 210, 1_150_000), ("Medellín", "New York", 340, 1_850_000),
    ("Cali", "Miami", 230, 1_200_000), ("Cali", "Madrid", 630, 3_250_000),
    ("Cartagena de Indias", "Miami", 175, 1_050_000), ("Cartagena de Indias", "New York", 300, 1_750_000),
    ("Pereira", "Miami", 225, 1_250_000), ("Pereira", "Madrid", 640, 3_300_000),
]

HORAS_SALIDA = [time(h, m) for h in range(5, 23) for m in (0, 15, 30, 45)]


def _precio(base, rng):
    """Precio con variación de ±25 %, redondeado a miles."""
    return Decimal(int(round(base * rng.uniform(0.75, 1.25), -3)))


def _vendidos(capacidad, rng):
    """La mitad de los vuelos sin ventas (editables); el resto con ocupación variada."""
    if rng.random() < 0.5:
        return 0
    return rng.randint(1, int(capacidad * 0.9))


class Command(BaseCommand):
    help = "Carga vuelos simulados nacionales e internacionales (con regreso) en fechas futuras."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=30, help="Ventana de días hacia adelante (por defecto 30).")
        parser.add_argument("--nacionales", type=int, default=40, help="Cantidad de vuelos nacionales.")
        parser.add_argument("--internacionales", type=int, default=12,
                            help="Cantidad de vuelos internacionales de ida (cada uno con su regreso).")
        parser.add_argument("--semilla", type=int, default=None, help="Semilla aleatoria para resultados repetibles.")
        parser.add_argument("--limpiar", action="store_true",
                            help="Borra antes los vuelos futuros sin tiquetes vendidos del usuario creador.")

    def _creador(self):
        usuario = (Usuario.objects.filter(rol=Usuario.Rol.ADMINISTRADOR).order_by("pk").first()
                   or Usuario.objects.filter(rol=Usuario.Rol.ROOT).order_by("pk").first())
        if usuario is None:
            raise CommandError("No hay usuario root ni administrador. Ejecuta primero `python manage.py migrate`.")
        return usuario

    @transaction.atomic
    def handle(self, *args, **opciones):
        if opciones["dias"] < 2:
            raise CommandError("--dias debe ser al menos 2.")
        rng = random.Random(opciones["semilla"])
        creador = self._creador()
        ahora = timezone.now()
        hoy = date.today()

        if opciones["limpiar"]:
            # Solo vuelos de ida: borrar la ida elimina también su regreso (CASCADE).
            borrables = Vuelo.objects.filter(creado_por=creador, salida__gt=ahora, tiquetes_vendidos=0,
                                             vuelo_ida__isnull=True)
            total, _ = borrables.delete()
            self.stdout.write(f"Vuelos borrados: {total}")

        def salida_local():
            dia = hoy + timedelta(days=rng.randint(1, opciones["dias"]))
            return datetime.combine(dia, rng.choice(HORAS_SALIDA))

        nacionales = 0
        for _ in range(opciones["nacionales"]):
            origen, destino, minutos, base = rng.choice(RUTAS_NACIONALES)
            minutos += rng.choice([-5, 0, 0, 5, 10])
            salida_utc = reglas.a_utc(salida_local(), reglas.TZ_COLOMBIA)
            if salida_utc <= ahora:
                continue
            Vuelo.objects.create(
                tipo=Vuelo.Tipo.NACIONAL, origen=origen, destino=destino,
                salida=salida_utc, llegada=salida_utc + timedelta(minutes=minutos),
                duracion_minutos=minutos, costo_persona=_precio(base, rng),
                capacidad=reglas.CAPACIDAD_NACIONAL,
                tiquetes_vendidos=_vendidos(reglas.CAPACIDAD_NACIONAL, rng), creado_por=creador,
            )
            nacionales += 1

        internacionales = 0
        for _ in range(opciones["internacionales"]):
            origen, destino, minutos, base = rng.choice(RUTAS_INTERNACIONALES)
            salida_ida, llegada_ida = reglas.calcular_llegada_internacional(
                salida_local(), reglas.zona_de(origen), destino, minutos)
            if salida_ida <= ahora:
                continue
            ida = Vuelo.objects.create(
                tipo=Vuelo.Tipo.INTERNACIONAL, origen=origen, destino=destino,
                salida=salida_ida, llegada=llegada_ida, duracion_minutos=minutos,
                costo_persona=_precio(base, rng), capacidad=reglas.CAPACIDAD_INTERNACIONAL,
                tiquetes_vendidos=_vendidos(reglas.CAPACIDAD_INTERNACIONAL, rng), creado_por=creador,
            )
            # Regreso entre 3 y 15 días después de la llegada, en hora local del destino.
            zona_destino = reglas.zona_de(destino)
            dia_regreso = llegada_ida.astimezone(zona_destino).date() + timedelta(days=rng.randint(3, 15))
            minutos_r = minutos + rng.choice([-20, -10, 0, 15, 30])
            salida_r, llegada_r = reglas.calcular_llegada_internacional(
                datetime.combine(dia_regreso, rng.choice(HORAS_SALIDA)), zona_destino, origen, minutos_r)
            Vuelo.objects.create(
                tipo=Vuelo.Tipo.INTERNACIONAL, origen=destino, destino=origen,
                salida=salida_r, llegada=llegada_r, duracion_minutos=minutos_r,
                costo_persona=_precio(base, rng), capacidad=reglas.CAPACIDAD_INTERNACIONAL,
                tiquetes_vendidos=_vendidos(reglas.CAPACIDAD_INTERNACIONAL, rng),
                creado_por=creador, vuelo_ida=ida,
            )
            internacionales += 2

        self.stdout.write(self.style.SUCCESS(
            f"Vuelos creados: {nacionales} nacionales y {internacionales} internacionales "
            f"({internacionales // 2} con regreso). Creador: {creador.username}."))
