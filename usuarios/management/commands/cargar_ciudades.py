from django.core.management.base import BaseCommand

from usuarios.models import Ciudad, Departamento

CIUDADES = {
    "Amazonas": ["Leticia"],
    "Antioquia": ["Medellín", "Bello", "Envigado", "Itagüí"],
    "Arauca": ["Arauca"],
    "Atlántico": ["Barranquilla", "Soledad"],
    "Bogotá D.C.": ["Bogotá"],
    "Bolívar": ["Cartagena"],
    "Boyacá": ["Tunja", "Duitama", "Sogamoso"],
    "Caldas": ["Manizales"],
    "Caquetá": ["Florencia"],
    "Casanare": ["Yopal"],
    "Cauca": ["Popayán"],
    "Cesar": ["Valledupar"],
    "Chocó": ["Quibdó"],
    "Córdoba": ["Montería"],
    "Cundinamarca": ["Soacha", "Zipaquirá", "Girardot", "Fusagasugá"],
    "Guainía": ["Inírida"],
    "Guaviare": ["San José del Guaviare"],
    "Huila": ["Neiva"],
    "La Guajira": ["Riohacha"],
    "Magdalena": ["Santa Marta"],
    "Meta": ["Villavicencio"],
    "Nariño": ["Pasto"],
    "Norte de Santander": ["Cúcuta"],
    "Putumayo": ["Mocoa"],
    "Quindío": ["Armenia"],
    "Risaralda": ["Pereira", "Dosquebradas"],
    "San Andrés y Providencia": ["San Andrés"],
    "Santander": ["Bucaramanga", "Floridablanca"],
    "Sucre": ["Sincelejo"],
    "Tolima": ["Ibagué"],
    "Valle del Cauca": ["Cali", "Palmira", "Buenaventura", "Tuluá"],
    "Vaupés": ["Mitú"],
    "Vichada": ["Puerto Carreño"],
}


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