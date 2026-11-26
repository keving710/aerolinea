"""Agrega un vuelo de regreso a cada vuelo programado que todavía no tiene uno.

Uso:
    python manage.py agregar_regresos            # crea los regresos que falten
    python manage.py agregar_regresos --simular  # solo muestra cuántos crearía
    python manage.py agregar_regresos --semilla 7

Es idempotente: cada vuelo se empareja con un vuelo de ruta contraria (mismo tipo) que salga
después de su llegada; solo si no hay pareja se crea el regreso. Ejecutarlo dos veces no duplica.
Los internacionales quedan vinculados (vuelo_ida) como los crea el administrador; los nacionales
se crean como vuelos independientes de ruta contraria, que el buscador ofrece como «ida y vuelta».
"""
import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from vuelos import reglas
from vuelos.models import Vuelo

HORAS = [time(h, m) for h in range(6, 22) for m in (0, 30)]


def _redondear(valor):
    return Decimal(int(round(float(valor), -3))) or Decimal(1000)


def crear_regreso(ida, rng, creador=None):
    """Crea y devuelve el regreso de `ida` (sin comprobar si ya existe)."""
    internacional = ida.tipo == Vuelo.Tipo.INTERNACIONAL
    zona_destino = ida.zona_destino
    dias = rng.randint(3, 15) if internacional else rng.randint(2, 7)
    dia = ida.llegada.astimezone(zona_destino).date() + timedelta(days=dias)
    naive = datetime.combine(dia, rng.choice(HORAS))
    minutos = max(30, ida.duracion_minutos + rng.choice([-10, 0, 0, 10]))
    if internacional:
        salida, llegada = reglas.calcular_llegada_internacional(naive, zona_destino, ida.origen, minutos)
    else:
        salida = reglas.a_utc(naive, reglas.TZ_COLOMBIA)
        llegada = salida + timedelta(minutes=minutos)
    return Vuelo.objects.create(
        tipo=ida.tipo, origen=ida.destino, destino=ida.origen, salida=salida, llegada=llegada,
        duracion_minutos=minutos, costo_persona=_redondear(ida.costo_persona * Decimal(str(rng.uniform(0.9, 1.1)))),
        capacidad=ida.capacidad, creado_por=creador or ida.creado_por,
        vuelo_ida=ida if internacional else None)


def agregar_regresos(rng=None, simular=False, ahora=None):
    """Devuelve la lista de regresos creados (o de vuelos a los que se les crearía, si `simular`)."""
    rng = rng or random.Random()
    ahora = ahora or timezone.now()
    vuelos = list(Vuelo.objects.filter(estado=Vuelo.Estado.PROGRAMADO, salida__gt=ahora)
                  .select_related("vuelo_ida").order_by("salida", "pk"))
    usados = set()
    for v in vuelos:  # Parejas ya vinculadas por el administrador.
        if v.vuelo_ida_id:
            usados.update((v.pk, v.vuelo_ida_id))
    pendientes = []
    for v in vuelos:
        if v.pk in usados:
            continue
        pareja = next((o for o in vuelos if o.pk not in usados and o.pk != v.pk and o.tipo == v.tipo
                       and (o.origen, o.destino) == (v.destino, v.origen) and o.salida > v.llegada), None)
        usados.add(v.pk)
        if pareja:
            usados.add(pareja.pk)
        else:
            pendientes.append(v)
    if simular:
        return pendientes
    return [crear_regreso(v, rng) for v in pendientes]


class Command(BaseCommand):
    help = "Agrega un vuelo de regreso a cada vuelo programado que no tenga uno."

    def add_arguments(self, parser):
        parser.add_argument("--simular", action="store_true", help="Solo cuenta los regresos que se crearían.")
        parser.add_argument("--semilla", type=int, default=None, help="Semilla aleatoria para resultados repetibles.")

    @transaction.atomic
    def handle(self, *args, **opciones):
        resultado = agregar_regresos(random.Random(opciones["semilla"]), opciones["simular"])
        if opciones["simular"]:
            self.stdout.write(f"Se crearían {len(resultado)} vuelos de regreso.")
        else:
            self.stdout.write(self.style.SUCCESS(f"Vuelos de regreso creados: {len(resultado)}."))
