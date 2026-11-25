from django.core.management.base import BaseCommand

from reservas import servicios


class Command(BaseCommand):
    help = "Marca como realizados los vuelos que ya salieron y libera las reservas vencidas (24 h)."

    def handle(self, *args, **opciones):
        r = servicios.mantenimiento()
        self.stdout.write(self.style.SUCCESS(
            f"Vuelos marcados como realizados: {r['realizados']}. Reservas liberadas: {r['liberadas']}."))
