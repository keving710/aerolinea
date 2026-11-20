from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from vuelos import reglas
from vuelos.catalogo import disponibles
from vuelos.models import Vuelo


class CargarVuelosDemo(TestCase):
    def cargar(self, *args):
        call_command("cargar_vuelos_demo", "--semilla", "7", *args, stdout=StringIO())

    def test_crea_vuelos_validos_y_publicados(self):
        self.cargar("--nacionales", "20", "--internacionales", "5")
        self.assertEqual(Vuelo.objects.filter(tipo="nacional").count(), 20)
        self.assertEqual(Vuelo.objects.filter(tipo="internacional").count(), 10)
        ahora = timezone.now()
        for v in Vuelo.objects.all():
            self.assertGreater(v.salida, ahora)
            self.assertGreater(v.llegada, v.salida)
            self.assertNotEqual(v.origen, v.destino)
            self.assertLessEqual(v.tiquetes_vendidos, v.capacidad)
            if v.tipo == "nacional":
                self.assertIn(v.origen, reglas.CIUDADES_NACIONALES)
                self.assertEqual(v.capacidad, reglas.CAPACIDAD_NACIONAL)
        self.assertTrue(disponibles().exists())

    def test_cada_internacional_tiene_regreso_posterior(self):
        self.cargar("--nacionales", "0", "--internacionales", "4")
        idas = Vuelo.objects.filter(vuelo_ida__isnull=True)
        self.assertEqual(idas.count(), 4)
        for ida in idas:
            regreso = ida.vuelo_regreso
            self.assertEqual((regreso.origen, regreso.destino), (ida.destino, ida.origen))
            self.assertGreater(regreso.salida, ida.llegada)

    def test_limpiar_reemplaza_los_vuelos(self):
        self.cargar("--nacionales", "10", "--internacionales", "2")
        Vuelo.objects.update(tiquetes_vendidos=0)
        self.cargar("--limpiar", "--nacionales", "3", "--internacionales", "1")
        self.assertEqual(Vuelo.objects.count(), 5)
