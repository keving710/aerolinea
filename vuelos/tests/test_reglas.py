from datetime import datetime, time

from django.test import SimpleTestCase

from vuelos import reglas


class ReglasTests(SimpleTestCase):
    def test_duracion_nacional_mismo_dia(self):
        salida = datetime(2027, 3, 1, 8, 0)
        minutos, llegada = reglas.duracion_nacional(salida, time(9, 15))
        self.assertEqual(minutos, 75)

    def test_llegada_menor_es_dia_siguiente(self):
        salida = datetime(2027, 3, 1, 23, 30)
        minutos, llegada = reglas.duracion_nacional(salida, time(0, 45))
        self.assertEqual(minutos, 75)
        self.assertEqual(llegada.day, 2)

    def test_horas_iguales_error(self):
        with self.assertRaises(ValueError):
            reglas.duracion_nacional(datetime(2027, 3, 1, 8, 0), time(8, 0))

    def test_madrid_invierno(self):
        s, l = reglas.calcular_llegada_internacional(
            datetime(2027, 1, 15, 10, 0), reglas.TZ_COLOMBIA, "Madrid", 9 * 60)
        self.assertEqual(reglas.formatear(l, reglas.zona_de("Madrid")), "16/01/2027 01:00")

    def test_madrid_verano(self):
        s, l = reglas.calcular_llegada_internacional(
            datetime(2027, 7, 15, 10, 0), reglas.TZ_COLOMBIA, "Madrid", 9 * 60)
        self.assertEqual(reglas.formatear(l, reglas.zona_de("Madrid")), "16/07/2027 02:00")

    def test_buenos_aires(self):
        s, l = reglas.calcular_llegada_internacional(
            datetime(2027, 1, 15, 10, 0), reglas.TZ_COLOMBIA, "Buenos Aires", 6 * 60)
        self.assertEqual(reglas.formatear(l, reglas.zona_de("Buenos Aires")), "15/01/2027 18:00")

    def test_listas(self):
        self.assertEqual(len(reglas.CIUDADES_NACIONALES), 32)
        self.assertEqual(len(reglas.ORIGENES_INTERNACIONALES), 5)
        self.assertEqual(len(reglas.DESTINOS_INTERNACIONALES), 5)
