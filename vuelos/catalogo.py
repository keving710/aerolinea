"""Consulta pública compartida por portada, búsqueda y detalle."""
from datetime import datetime, time, timedelta

from django.db.models import F, Q
from django.utils import timezone

from . import reglas
from .models import Vuelo


def disponibles():
    return Vuelo.objects.filter(estado=Vuelo.Estado.PROGRAMADO, salida__gt=timezone.now(),
                               capacidad__gt=F("tiquetes_vendidos") + F("cupos_reservados"))


def buscar(datos):
    qs = disponibles()
    for campo in ("origen", "destino", "tipo"):
        if datos.get(campo):
            qs = qs.filter(**{campo: datos[campo]})
    if datos.get("codigo"):
        qs = qs.filter(codigo__icontains=datos["codigo"])
    for nombre, lookup in (("costo_min", "costo_persona__gte"), ("costo_max", "costo_persona__lte"),
                           ("duracion_min", "duracion_minutos__gte"), ("duracion_max", "duracion_minutos__lte")):
        if datos.get(nombre) is not None:
            qs = qs.filter(**{lookup: datos[nombre]})
    # Fecha/hora interpretadas en la ciudad de salida, incluidos regresos y DST.
    # Cada zona genera un predicado SQL, sin cargar todos los vuelos en memoria.
    if datos.get("fecha") or datos.get("hora"):
        from django.db.models.functions import TruncTime
        condiciones = Q(pk__in=[])
        grupos = [(Q(origen__in=reglas.CIUDADES_NACIONALES), reglas.TZ_COLOMBIA)]
        grupos += [(Q(origen=ciudad), reglas.zona_de(ciudad)) for ciudad in reglas.DESTINOS_INTERNACIONALES]
        for i, (condicion, zona) in enumerate(grupos):
            if datos.get("fecha"):
                fecha = datos["fecha"]
                inicio = timezone.make_aware(datetime.combine(fecha, time.min), zona)
                fin = timezone.make_aware(datetime.combine(fecha + timedelta(days=1), time.min), zona)
                condicion &= Q(salida__gte=inicio, salida__lt=fin)
            if datos.get("hora"):
                alias = f"hora_local_{i}"
                qs = qs.alias(**{alias: TruncTime("salida", tzinfo=zona)})
                condicion &= Q(**{alias: datos["hora"]})
            condiciones |= condicion
        qs = qs.filter(condiciones)
    return qs.order_by(datos.get("orden") or "salida", "pk")
