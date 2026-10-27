"""Reglas de negocio de los vuelos (RF-AV-02 a RF-AV-06). Sin dependencias de Django."""
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

TZ_COLOMBIA = ZoneInfo("America/Bogota")
UTC = dt_timezone.utc

CAPACIDAD_NACIONAL = 150
CAPACIDAD_INTERNACIONAL = 250

CIUDADES_NACIONALES = [
    "Arauca", "Armenia", "Barranquilla", "Bogotá", "Bucaramanga", "Cali",
    "Cartagena de Indias", "Cúcuta", "Florencia", "Ibagué", "Inírida", "Leticia",
    "Manizales", "Medellín", "Mitú", "Mocoa", "Montería", "Neiva", "Pasto",
    "Pereira", "Popayán", "Puerto Carreño", "Quibdó", "Riohacha", "San Andrés",
    "San José del Guaviare", "Santa Marta", "Sincelejo", "Tunja", "Valledupar",
    "Villavicencio", "Yopal",
]

ORIGENES_INTERNACIONALES = ["Pereira", "Bogotá", "Medellín", "Cali", "Cartagena de Indias"]

# Destino internacional -> zona horaria IANA (maneja horario de verano automáticamente).
ZONAS_DESTINO = {
    "Madrid": "Europe/Madrid",
    "Londres": "Europe/London",
    "New York": "America/New_York",
    "Buenos Aires": "America/Argentina/Buenos_Aires",
    "Miami": "America/New_York",
}
DESTINOS_INTERNACIONALES = list(ZONAS_DESTINO)


def zona_de(ciudad):
    """Zona horaria de una ciudad (Colombia por defecto)."""
    return ZoneInfo(ZONAS_DESTINO.get(ciudad, "America/Bogota"))


def a_utc(naive, zona):
    """Interpreta una fecha-hora sin zona como hora local de `zona` y la pasa a UTC."""
    return naive.replace(tzinfo=zona).astimezone(UTC)


def duracion_nacional(salida, llegada):
    """Minutos entre dos horas del mismo día (hora local). Si la llegada es menor, es del día siguiente.

    Devuelve (duracion_minutos, llegada_datetime). Lanza ValueError si son iguales.
    """
    if llegada == salida.time():
        raise ValueError("La hora de llegada no puede ser igual a la de salida.")
    llegada_dt = salida.replace(hour=llegada.hour, minute=llegada.minute)
    if llegada_dt < salida:
        llegada_dt += timedelta(days=1)
    return int((llegada_dt - salida).total_seconds() // 60), llegada_dt


def calcular_llegada_internacional(salida_local_naive, origen_zona, destino, duracion_min):
    """Hora de llegada en UTC y en la hora local del destino."""
    salida_utc = a_utc(salida_local_naive, origen_zona)
    llegada_utc = salida_utc + timedelta(minutes=duracion_min)
    return salida_utc, llegada_utc


def formatear(dt_utc, zona):
    return dt_utc.astimezone(zona).strftime("%d/%m/%Y %H:%M")


def formatear_duracion(minutos):
    h, m = divmod(minutos, 60)
    return f"{h} h {m:02d} min"
