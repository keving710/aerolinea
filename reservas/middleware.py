import logging
import time

from django.db import DatabaseError

logger = logging.getLogger(__name__)

INTERVALO_SEGUNDOS = 30
_ultimo = 0.0


class MantenimientoMiddleware:
    """Marca vuelos realizados y libera reservas vencidas sin necesidad de un proceso aparte.

    Se ejecuta como máximo cada 30 segundos por proceso y nunca interrumpe la respuesta.
    Las operaciones de compra y reserva además liberan lo vencido de sus propios vuelos.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        global _ultimo
        ahora = time.monotonic()
        if request.method == "GET" and ahora - _ultimo >= INTERVALO_SEGUNDOS and not request.path.startswith(("/static/", "/media/")):
            _ultimo = ahora
            try:
                from . import servicios
                servicios.mantenimiento()
            except DatabaseError:
                logger.exception("No se pudo ejecutar el mantenimiento de reservas")
        return self.get_response(request)
