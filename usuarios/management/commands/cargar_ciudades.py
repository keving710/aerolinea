from django.core.management.base import BaseCommand

from usuarios.datos_ciudades import CIUDADES
from usuarios.models import Ciudad, Departamento



class Command(BaseCommand):
    help = "Carga departamentos y ciudades principales de Colombia."

    def handle(self, *args, **options):
        total = 0
        for nombre_dep, ciudades in CIUDADES.items():
            dep, _ = Departamento.objects.get_or_create(nombre=nombre_dep)
            for nombre in ciudades:
                _, creada = Ciudad.objects.get_or_create(nombre=nombre, departamento=dep)
                total += creada
        self.stdout.write(self.style.SUCCESS(f"Ciudades nuevas: {total}"))