from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase

from finanzas.models import Tarjeta
from reservas import servicios
from reservas.models import Reserva, Tiquete
from usuarios.models import Usuario
from vuelos.models import Vuelo

from .base import BaseReservas, viajero


class ClientesDemoTests(TestCase):
    def cargar(self):
        call_command("cargar_clientes_demo", stdout=StringIO())

    def test_cliente_cinco_ya_tiene_cinco_tiquetes_y_el_sexto_se_rechaza(self):
        self.cargar()
        cliente = Usuario.objects.get(username="cliente_cinco")
        tiquetes = Tiquete.objects.filter(reserva__cliente=cliente, estado="activo")
        self.assertEqual(tiquetes.count(), 5)
        vuelo = tiquetes.first().vuelo
        self.assertEqual({t.vuelo_id for t in tiquetes}, {vuelo.pk})
        with self.assertRaisesMessage(ValidationError, "Máximo 5 tiquetes"):
            servicios.comprar(cliente, [{"vuelo": vuelo.codigo, "regreso": "",
                                         "viajeros": [viajero("9999991")]}], cliente.tarjetas.get())
        self.assertEqual(tiquetes.count(), 5)

    def test_cliente_saldo_solo_tiene_mil_pesos_y_no_puede_comprar(self):
        self.cargar()
        cliente = Usuario.objects.get(username="cliente_saldo")
        tarjeta = cliente.tarjetas.get()
        self.assertEqual(tarjeta.saldo, 1000)
        vuelo = Vuelo.objects.filter(creado_por__username="admin_demo", origen="Pereira", destino="Bogotá").first()
        with self.assertRaisesMessage(ValidationError, "saldo"):
            servicios.comprar(cliente, [{"vuelo": vuelo.codigo, "regreso": "",
                                         "viajeros": [viajero("9999992")]}], tarjeta)
        tarjeta.refresh_from_db()
        self.assertEqual(tarjeta.saldo, 1000)
        self.assertFalse(Reserva.objects.filter(cliente=cliente).exists())

    def test_es_repetible_y_deja_credenciales_validas(self):
        self.cargar()
        antes = (Vuelo.objects.count(), Tiquete.objects.count(), Tarjeta.objects.count())
        self.cargar()
        self.assertEqual((Vuelo.objects.count(), Tiquete.objects.count(), Tarjeta.objects.count()), antes)
        for username in ("admin_demo", "cliente_cinco", "cliente_saldo", "cliente_demo"):
            self.assertTrue(self.client.login(username=username, password="Demo2026!"), username)
            self.assertTrue(Usuario.objects.get(username=username).perfil_completo)
        # La tarjeta muestra su número completo ficticio.
        self.assertEqual(Tarjeta.objects.get(cliente__username="cliente_cinco").numero_visible, "4111 1111 1111 1111")


class AgregarRegresosTests(BaseReservas):
    def test_crea_regreso_para_cada_vuelo_y_no_duplica(self):
        nacional = self.crear_vuelo(dias=10, origen="Pereira", destino="Medellín")
        internacional = self.crear_vuelo(dias=12, origen="Bogotá", destino="Miami", tipo="internacional")
        total = Vuelo.objects.count()
        salida = StringIO()
        call_command("agregar_regresos", "--simular", stdout=salida)
        self.assertEqual(Vuelo.objects.count(), total)
        call_command("agregar_regresos", "--semilla", "1", stdout=StringIO())
        r_nac = Vuelo.objects.get(origen="Medellín", destino="Pereira")
        r_int = Vuelo.objects.get(origen="Miami", destino="Bogotá")
        self.assertGreater(r_nac.salida, nacional.llegada)
        self.assertGreater(r_int.salida, internacional.llegada)
        self.assertEqual(r_int.vuelo_ida, internacional)
        self.assertIsNone(r_nac.vuelo_ida)
        total = Vuelo.objects.count()
        call_command("agregar_regresos", stdout=StringIO())
        self.assertEqual(Vuelo.objects.count(), total)

    def test_no_crea_regreso_si_ya_existe_uno(self):
        ida = self.crear_vuelo(dias=5, origen="Cali", destino="Bogotá")
        self.crear_vuelo(dias=9, origen="Bogotá", destino="Cali")
        call_command("agregar_regresos", stdout=StringIO())
        self.assertEqual(Vuelo.objects.filter(origen="Bogotá", destino="Cali").count(), 1)
        self.assertEqual(Vuelo.objects.filter(origen="Cali", destino="Bogotá").count(), 1)
        self.assertTrue(ida.pk)
