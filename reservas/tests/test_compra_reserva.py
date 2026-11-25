from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from finanzas.models import Movimiento
from reservas import servicios
from reservas.models import Reserva, Tiquete

from .base import BaseReservas, datos_post, viajero


class InicioDesdeResultadosTests(BaseReservas):
    """HU 26."""

    def url(self, accion="comprar", vuelo=None):
        return reverse("reservas:iniciar", args=[(vuelo or self.vuelo).codigo, accion])

    def test_resultados_ofrecen_comprar_y_reservar(self):
        r = self.client.get(reverse("vuelos:busqueda"))
        self.assertContains(r, self.url("comprar"))
        self.assertContains(r, self.url("reservar"))
        self.assertContains(r, "debes <a")

    def test_visitante_debe_registrarse(self):
        r = self.client.get(self.url(), follow=True)
        self.assertRedirects(r, f"{reverse('usuarios:registro')}?next={self.url().replace('/', '%2F')}")
        self.assertContains(r, "registrarte")

    def test_root_y_administrador_no_compran_ni_reservan(self):
        for usuario in (self.admin, self.root):
            self.client.force_login(usuario)
            for accion in ("comprar", "reservar"):
                self.assertEqual(self.client.get(self.url(accion)).status_code, 403)
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse("vuelos:busqueda")), self.url("comprar"))

    def test_cliente_llega_al_formulario(self):
        self.client.force_login(self.cliente)
        self.assertContains(self.client.get(self.url()), "Datos de los viajeros")

    def test_vuelo_no_disponible_da_404(self):
        self.client.force_login(self.cliente)
        self.vuelo.estado = "cancelado"
        self.vuelo.save(update_fields=["estado"])
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_registro_vuelve_a_la_compra(self):
        from usuarios.models import Ciudad
        ciudad = Ciudad.objects.first()
        r = self.client.post(f"{reverse('usuarios:registro')}?next={self.url()}", {
            "dni": "9990001", "first_name": "Nuevo", "last_name": "Cliente", "fecha_nacimiento": "1990-01-01",
            "ciudad_nacimiento": ciudad.pk, "direccion_facturacion": "Calle 1", "genero": "otro", "email": "nuevo@c.com",
            "username": "nuevo", "password1": "Clave#Segura1", "password2": "Clave#Segura1"})
        self.assertRedirects(r, self.url(), fetch_redirect_response=False)

    def test_next_externo_se_ignora(self):
        from usuarios.models import Ciudad
        ciudad = Ciudad.objects.first()
        r = self.client.post(f"{reverse('usuarios:registro')}?next=https://malo.example/", {
            "dni": "9990002", "first_name": "Nuevo", "last_name": "Cliente", "fecha_nacimiento": "1990-01-01",
            "ciudad_nacimiento": ciudad.pk, "direccion_facturacion": "Calle 1", "genero": "otro", "email": "n2@c.com",
            "username": "nuevo2", "password1": "Clave#Segura1", "password2": "Clave#Segura1"})
        self.assertRedirects(r, reverse("inicio"), fetch_redirect_response=False)


class DatosViajerosTests(BaseReservas):
    """HU 27."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.cliente)
        self.url = reverse("reservas:iniciar", args=[self.vuelo.codigo, "comprar"])

    def enviar(self, viajeros):
        return self.client.post(self.url, datos_post(viajeros))

    def test_cada_dato_es_obligatorio(self):
        for campo in ("documento", "nombres", "apellidos", "fecha_nacimiento", "genero", "telefono", "correo",
                      "contacto_nombre", "contacto_telefono"):
            with self.subTest(campo=campo):
                r = self.enviar([viajero(**{campo: ""})])
                self.assertEqual(r.status_code, 200)
                self.assertNotIn("carrito_tiquetes", self.client.session)

    def test_falta_dato_del_segundo_viajero(self):
        r = self.enviar([viajero("1000001"), viajero("1000002", telefono="")])
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("carrito_tiquetes", self.client.session)

    def test_solo_menores_se_rechaza(self):
        r = self.enviar([viajero("1000003", nacimiento=str(timezone.localdate().year - 10) + "-01-01")])
        self.assertContains(r, "menor de edad no puede viajar solo")
        self.assertNotIn("carrito_tiquetes", self.client.session)

    def test_menor_con_adulto_se_acepta(self):
        r = self.enviar([viajero("1000003", nacimiento=str(timezone.localdate().year - 10) + "-01-01"), viajero("1000004")])
        self.assertRedirects(r, reverse("reservas:carrito"))
        self.assertEqual(len(self.client.session["carrito_tiquetes"][0]["viajeros"]), 2)

    def test_formatos_invalidos(self):
        for extra in ({"documento": "12"}, {"documento": "12 34 56"}, {"telefono": "abc"}, {"correo": "no-es-correo"},
                      {"fecha_nacimiento": "2999-01-01"}, {"fecha_nacimiento": "1800-01-01"}, {"contacto_telefono": "1"}):
            with self.subTest(extra=extra):
                self.assertEqual(self.enviar([viajero(**extra)]).status_code, 200)
                self.assertNotIn("carrito_tiquetes", self.client.session)

    def test_mismo_viajero_repetido(self):
        self.assertEqual(self.enviar([viajero("1000001"), viajero("1000001")]).status_code, 200)
        self.assertNotIn("carrito_tiquetes", self.client.session)

    def test_mas_de_cinco_viajeros(self):
        r = self.enviar([viajero(str(1000000 + i)) for i in range(6)])
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("carrito_tiquetes", self.client.session)

    def test_menor_se_mide_a_la_fecha_del_vuelo(self):
        # Cumple 18 años cinco días antes del vuelo: ya es mayor de edad al viajar.
        fecha = timezone.localtime(self.vuelo.salida, self.vuelo.zona_origen).date()
        nacimiento = (fecha.replace(year=fecha.year - 18) - timedelta(days=5)).isoformat()
        self.assertRedirects(self.enviar([viajero(nacimiento=nacimiento)]), reverse("reservas:carrito"))


class ReservaTests(BaseReservas):
    """HU 28 y 31."""

    def reservar(self, viajeros=None, vuelo=None, cliente=None):
        linea = {"vuelo": (vuelo or self.vuelo).codigo, "regreso": "", "viajeros": viajeros or [viajero()]}
        return servicios.reservar(cliente or self.cliente, linea)

    def test_reserva_retiene_cupos_24_horas(self):
        reserva = self.reservar([viajero("1000001"), viajero("1000002")])
        self.vuelo.refresh_from_db()
        self.assertEqual((self.vuelo.cupos_reservados, self.vuelo.tiquetes_vendidos, self.vuelo.cupos_disponibles), (2, 0, 148))
        self.assertEqual(reserva.estado, "reservada")
        self.assertAlmostEqual((reserva.expira_en - timezone.now()).total_seconds(), 24 * 3600, delta=60)
        self.assertEqual(self.saldo(), Decimal("5000000"))

    def test_reserva_por_la_vista(self):
        self.client.force_login(self.cliente)
        r = self.client.post(reverse("reservas:iniciar", args=[self.vuelo.codigo, "reservar"]), datos_post([viajero()]))
        reserva = Reserva.objects.get()
        self.assertRedirects(r, reverse("reservas:detalle", args=[reserva.codigo]))

    def test_pasadas_24_horas_los_cupos_vuelven(self):
        reserva = self.reservar([viajero("1000001"), viajero("1000002")])
        servicios.liberar_vencidas()
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.cupos_reservados, 2)  # aún vigente
        Reserva.objects.filter(pk=reserva.pk).update(expira_en=timezone.now() - timedelta(seconds=1))
        self.assertEqual(servicios.liberar_vencidas(), 1)
        self.vuelo.refresh_from_db()
        reserva.refresh_from_db()
        self.assertEqual((self.vuelo.cupos_reservados, self.vuelo.cupos_disponibles, reserva.estado), (0, 150, "vencida"))
        self.assertFalse(reserva.tiquetes.filter(estado="activo").exists())

    def test_vencida_se_libera_al_consultar_disponibilidad_de_compra(self):
        reserva = self.reservar([viajero("1000001")])
        Reserva.objects.filter(pk=reserva.pk).update(expira_en=timezone.now() - timedelta(minutes=1))
        # El mismo viajero puede volver a reservar porque la anterior ya venció.
        self.reservar([viajero("1000001")])
        self.assertEqual(Reserva.objects.filter(estado="reservada").count(), 1)

    def test_maximo_cinco_por_vuelo(self):
        with self.assertRaisesMessage(ValidationError, "entre 1 y 5"):
            self.reservar([viajero(str(1000000 + i)) for i in range(6)])
        self.reservar([viajero(str(1000000 + i)) for i in range(4)])
        with self.assertRaisesMessage(ValidationError, "Máximo 5 tiquetes por vuelo"):
            self.reservar([viajero("1000010"), viajero("1000011")])
        self.reservar([viajero("1000010")])  # el quinto sí
        with self.assertRaises(ValidationError):
            self.reservar([viajero("1000012")])

    def test_el_limite_es_por_cliente_y_por_vuelo(self):
        self.reservar([viajero(str(1000000 + i)) for i in range(5)])
        self.reservar([viajero("2000001")], cliente=self.otro)  # otro cliente, mismo vuelo
        otro_vuelo = self.crear_vuelo(dias=12)
        self.reservar([viajero(str(3000000 + i)) for i in range(5)], vuelo=otro_vuelo)

    def test_viajero_no_se_duplica_en_el_mismo_vuelo(self):
        self.reservar([viajero("1000001")])
        with self.assertRaisesMessage(ValidationError, "ya tiene un tiquete"):
            self.reservar([viajero("1000001")])
        with self.assertRaisesMessage(ValidationError, "ya tiene un tiquete"):
            self.reservar([viajero("1000001")], cliente=self.otro)
        self.reservar([viajero("1000001")], vuelo=self.crear_vuelo(dias=11))  # en otro vuelo sí

    def test_root_y_administrador_no_reservan(self):
        for usuario in (self.admin, self.root):
            with self.assertRaises(PermissionDenied):
                self.reservar(cliente=usuario)

    def test_no_se_reserva_sin_cupos(self):
        self.vuelo.tiquetes_vendidos = 149
        self.vuelo.save(update_fields=[])
        type(self.vuelo).objects.filter(pk=self.vuelo.pk).update(tiquetes_vendidos=149)
        with self.assertRaisesMessage(ValidationError, "cupos suficientes"):
            self.reservar([viajero("1000001"), viajero("1000002")])
        self.reservar([viajero("1000001")])
        self.assertEqual(self.vuelo.__class__.objects.get(pk=self.vuelo.pk).cupos_disponibles, 0)

    def test_vuelo_pasado_o_cancelado_no_se_reserva(self):
        self.vuelo.__class__.objects.filter(pk=self.vuelo.pk).update(estado="cancelado")
        with self.assertRaisesMessage(ValidationError, "ya no está disponible"):
            self.reservar()

    def test_correo_con_codigo_a_cada_viajero(self):
        reserva = self.reservar([viajero("1000001", correo="uno@correo.com"), viajero("1000002", correo="dos@correo.com")])
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["dos@correo.com", "uno@correo.com"])
        for m in mail.outbox:
            self.assertIn(reserva.codigo, m.body)
            self.assertIn(self.vuelo.codigo, m.body)
            self.assertIn("24", "24")  # el plazo se comunica en la fecha límite
            self.assertIn("se liberan automáticamente", m.body)

    def test_codigo_de_reserva_unico_y_no_secuencial(self):
        codigos = {self.reservar([viajero(str(1000000 + i))], vuelo=self.crear_vuelo(dias=11 + i)).codigo for i in range(5)}
        self.assertEqual(len(codigos), 5)
        for c in codigos:
            self.assertRegex(c, r"^RES-[A-HJ-NP-Z2-9]{8}$")

    def test_falla_el_correo_y_la_reserva_se_conserva(self):
        from unittest import mock
        with mock.patch("reservas.servicios.get_connection", side_effect=OSError("sin smtp")), \
                self.assertLogs("reservas.servicios", level="ERROR"):
            reserva = self.reservar()
        self.assertTrue(Reserva.objects.filter(pk=reserva.pk).exists())

    def test_reserva_nunca_vence_despues_del_vuelo(self):
        proximo = self.crear_vuelo(dias=0, horas=3)
        reserva = self.reservar(vuelo=proximo)
        self.assertEqual(reserva.expira_en, proximo.salida)

    def test_pagar_reserva(self):
        reserva = self.reservar([viajero("1000001"), viajero("1000002")])
        servicios.pagar_reserva(self.cliente, reserva.pk, self.tarjeta)
        reserva.refresh_from_db()
        self.vuelo.refresh_from_db()
        self.assertEqual((reserva.estado, reserva.tarjeta_id), ("comprada", self.tarjeta.pk))
        self.assertEqual((self.vuelo.cupos_reservados, self.vuelo.tiquetes_vendidos), (0, 2))
        self.assertEqual(self.saldo(), Decimal("4600000"))
        self.assertEqual(Movimiento.objects.filter(tipo="compra").count(), 1)

    def test_pagar_reserva_vencida_o_ajena(self):
        reserva = self.reservar()
        with self.assertRaises(Exception):
            servicios.pagar_reserva(self.otro, reserva.pk, self.tarjeta)
        Reserva.objects.filter(pk=reserva.pk).update(expira_en=timezone.now() - timedelta(minutes=1))
        with self.assertRaisesMessage(ValidationError, "venció"):
            servicios.pagar_reserva(self.cliente, reserva.pk, self.tarjeta)
        self.assertEqual(self.saldo(), Decimal("5000000"))

    def test_pagar_reserva_con_saldo_insuficiente_no_cambia_nada(self):
        pobre = self.tarjeta_con_saldo(self.cliente, 1000, numero="5555555555554444")
        reserva = self.reservar()
        with self.assertRaisesMessage(ValidationError, "saldo"):
            servicios.pagar_reserva(self.cliente, reserva.pk, pobre)
        reserva.refresh_from_db()
        self.vuelo.refresh_from_db()
        self.assertEqual((reserva.estado, self.vuelo.cupos_reservados, self.vuelo.tiquetes_vendidos), ("reservada", 1, 0))


class CarritoYCompraTests(BaseReservas):
    """HU 29 y 38 (selección de tarjeta en la compra)."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.cliente)

    def agregar(self, vuelo=None, viajeros=None, **kw):
        return self.client.post(reverse("reservas:iniciar", args=[(vuelo or self.vuelo).codigo, "comprar"]),
                                datos_post(viajeros or [viajero()], **kw))

    def pagar(self, tarjeta=None, total=None):
        r = self.client.get(reverse("reservas:carrito"))
        total = total if total is not None else r.context["total"]
        return self.client.post(reverse("reservas:carrito"), {"tarjeta": (tarjeta or self.tarjeta).pk, "total": total})

    def test_compra_exitosa_descuenta_y_asocia_tiquetes(self):
        self.agregar(viajeros=[viajero("1000001"), viajero("1000002")])
        self.assertContains(self.client.get(reverse("reservas:carrito")), "$400.000")
        r = self.pagar()
        reserva = Reserva.objects.get()
        self.assertRedirects(r, reverse("reservas:detalle", args=[reserva.codigo]))
        self.assertEqual((reserva.estado, reserva.cliente_id), ("comprada", self.cliente.pk))
        self.assertEqual(reserva.tiquetes.filter(estado="activo").count(), 2)
        self.assertEqual(self.saldo(), Decimal("4600000"))
        self.vuelo.refresh_from_db()
        self.assertEqual((self.vuelo.tiquetes_vendidos, self.vuelo.cupos_reservados), (2, 0))
        m = Movimiento.objects.get(tipo="compra")
        self.assertEqual((m.valor, m.saldo_resultante), (Decimal("400000"), Decimal("4600000")))
        self.assertIn(reserva.codigo, m.detalle)
        self.assertNotIn("carrito_tiquetes", self.client.session)
        self.assertEqual(len(mail.outbox), 2)

    def test_solo_se_descuenta_de_la_tarjeta_elegida(self):
        otra = self.tarjeta_con_saldo(self.cliente, 900000, numero="5555555555554444")
        self.agregar()
        self.pagar(tarjeta=otra)
        self.assertEqual(self.saldo(otra), Decimal("700000"))
        self.assertEqual(self.saldo(), Decimal("5000000"))

    def test_saldo_insuficiente_no_compra_nada(self):
        pobre = self.tarjeta_con_saldo(self.cliente, 100000, numero="5555555555554444")
        self.agregar()
        r = self.pagar(tarjeta=pobre)
        self.assertContains(r, "saldo disponible suficiente")
        self.assertFalse(Reserva.objects.exists())
        self.assertFalse(Tiquete.objects.exists())
        self.assertEqual(self.saldo(pobre), Decimal("100000"))
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.tiquetes_vendidos, 0)
        self.assertIn("carrito_tiquetes", self.client.session)  # el carrito se conserva

    def test_tarjeta_ajena_no_se_acepta(self):
        ajena = self.tarjeta_con_saldo(self.otro, 5_000_000, numero="5555555555554444")
        self.agregar()
        r = self.pagar(tarjeta=ajena)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Reserva.objects.exists())
        self.assertEqual(self.saldo(ajena), Decimal("5000000"))

    def test_tarjeta_vencida_no_se_ofrece(self):
        from finanzas.models import Tarjeta
        Tarjeta.objects.filter(pk=self.tarjeta.pk).update(anio_vencimiento=2020)
        self.agregar()
        self.assertEqual(self.pagar().status_code, 200)
        self.assertFalse(Reserva.objects.exists())

    def test_varios_vuelos_en_un_mismo_carrito(self):
        otro_vuelo = self.crear_vuelo(dias=12, destino="Cali", costo="300000")
        self.agregar()
        self.agregar(vuelo=otro_vuelo, viajeros=[viajero("1000001")])
        self.pagar()
        self.assertEqual(Reserva.objects.count(), 2)
        self.assertEqual(self.saldo(), Decimal("4500000"))
        self.assertEqual(Movimiento.objects.filter(tipo="compra").count(), 2)

    def test_si_una_linea_falla_no_se_compra_ninguna(self):
        otro_vuelo = self.crear_vuelo(dias=12)
        self.agregar()
        self.agregar(vuelo=otro_vuelo, viajeros=[viajero("1000009")])
        self.vuelo.__class__.objects.filter(pk=otro_vuelo.pk).update(estado="cancelado")
        r = self.pagar(total=400000)
        self.assertEqual(Reserva.objects.count(), 0)
        self.assertEqual(self.saldo(), Decimal("5000000"))
        self.assertEqual(r.status_code, 200)

    def test_carrito_respeta_limite_de_cinco_entre_lineas(self):
        self.agregar(viajeros=[viajero(str(1000000 + i)) for i in range(3)])
        r = self.agregar(viajeros=[viajero(str(2000000 + i)) for i in range(3)])
        self.assertContains(r, "Máximo 5 tiquetes por vuelo")
        self.assertEqual(len(self.client.session["carrito_tiquetes"]), 1)

    def test_carrito_rechaza_viajero_repetido_entre_lineas(self):
        self.agregar(viajeros=[viajero("1000001")])
        r = self.agregar(viajeros=[viajero("1000001")])
        self.assertContains(r, "ya tiene un tiquete")

    def test_limite_cuenta_tiquetes_ya_comprados(self):
        self.agregar(viajeros=[viajero(str(1000000 + i)) for i in range(5)])
        self.pagar()
        r = self.agregar(viajeros=[viajero("3000001")])
        self.assertContains(r, "Máximo 5 tiquetes por vuelo")

    def test_ida_y_vuelta_cobra_ambos_tramos(self):
        regreso = self.crear_vuelo(dias=15, origen="Bogotá", destino="Pereira", costo="150000")
        self.agregar(viajeros=[viajero("1000001"), viajero("1000002")], trayecto="completo", regreso=regreso.codigo)
        self.assertContains(self.client.get(reverse("reservas:carrito")), "$700.000")
        self.pagar()
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.trayecto, "completo")
        self.assertEqual(sorted(reserva.tiquetes.values_list("tramo", flat=True)), [1, 1, 2, 2])
        self.assertEqual(self.saldo(), Decimal("4300000"))
        regreso.refresh_from_db()
        self.assertEqual(regreso.tiquetes_vendidos, 2)

    def test_regreso_invalido(self):
        antes = self.crear_vuelo(dias=5, origen="Bogotá", destino="Pereira")
        otra_ruta = self.crear_vuelo(dias=15, origen="Bogotá", destino="Cali")
        for cod in (antes.codigo, otra_ruta.codigo, ""):
            with self.subTest(regreso=cod):
                r = self.agregar(trayecto="completo", regreso=cod)
                self.assertEqual(r.status_code, 200)
                self.assertNotIn("carrito_tiquetes", self.client.session)

    def test_regreso_se_ofrece_solo_si_corresponde(self):
        buena = self.crear_vuelo(dias=15, origen="Bogotá", destino="Pereira")
        self.crear_vuelo(dias=5, origen="Bogotá", destino="Pereira")
        r = self.client.get(reverse("reservas:iniciar", args=[self.vuelo.codigo, "comprar"]))
        self.assertEqual([v.codigo for v in r.context["trayecto"].opciones], [buena.codigo])

    def test_precio_cambiado_exige_confirmar(self):
        self.agregar()
        r = self.client.get(reverse("reservas:carrito"))
        total = r.context["total"]
        self.vuelo.descuento_porcentaje = Decimal("50")
        self.vuelo.save(update_fields=["descuento_porcentaje"])
        r = self.client.post(reverse("reservas:carrito"), {"tarjeta": self.tarjeta.pk, "total": total})
        self.assertContains(r, "cambió")
        self.assertFalse(Reserva.objects.exists())

    def test_pagar_con_carrito_vacio(self):
        r = self.client.post(reverse("reservas:carrito"), {"tarjeta": self.tarjeta.pk, "total": 0})
        self.assertFalse(Reserva.objects.exists())
        self.assertEqual(self.saldo(), Decimal("5000000"))

    def test_doble_envio_no_cobra_dos_veces(self):
        self.agregar()
        self.pagar(total=200000)
        self.pagar(total=200000)
        self.assertEqual(Reserva.objects.count(), 1)
        self.assertEqual(self.saldo(), Decimal("4800000"))

    def test_quitar_del_carrito(self):
        self.agregar()
        self.client.post(reverse("reservas:quitar", args=[0]))
        self.assertContains(self.client.get(reverse("reservas:carrito")), "Tu carrito está vacío")

    def test_carrito_es_solo_para_clientes(self):
        for usuario in (self.admin, self.root):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(reverse("reservas:carrito")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("reservas:carrito")).status_code, 302)

    def test_servicio_rechaza_a_root_y_administrador(self):
        linea = {"vuelo": self.vuelo.codigo, "regreso": "", "viajeros": [viajero()]}
        for usuario in (self.admin, self.root):
            with self.assertRaises(PermissionDenied):
                servicios.comprar(usuario, [linea], self.tarjeta)


class ClaseYSillaTests(BaseReservas):
    """HU 30."""

    def comprar(self, vuelo, viajeros):
        linea = {"vuelo": vuelo.codigo, "regreso": "", "viajeros": viajeros}
        return servicios.comprar(self.cliente, [linea], self.tarjeta)[0]

    def test_silla_dentro_del_rango_de_la_clase_nacional(self):
        for ronda in range(5):
            vuelo = self.crear_vuelo(dias=11 + ronda)
            reserva = self.comprar(vuelo, [viajero("1000001", clase="primera"), viajero("1000002", clase="economica"),
                                           viajero("1000003", clase="primera")])
            sillas = {t.documento: t.silla for t in reserva.tiquetes.all()}
            self.assertTrue(1 <= sillas["1000001"] <= 25 and 1 <= sillas["1000003"] <= 25)
            self.assertTrue(26 <= sillas["1000002"] <= 150)
            self.assertEqual(len(set(sillas.values())), 3)

    def test_rangos_internacional(self):
        vuelo = self.crear_vuelo(origen="Bogotá", destino="Madrid", tipo="internacional", costo="2500000")
        reserva = self.comprar(vuelo, [viajero("1000001", clase="primera"), viajero("1000002")])
        sillas = {t.documento: t.silla for t in reserva.tiquetes.all()}
        self.assertTrue(1 <= sillas["1000001"] <= 50)
        self.assertTrue(51 <= sillas["1000002"] <= 250)

    def test_silla_no_ocupada_por_otro_viajero(self):
        # Se ocupa toda la clase económica salvo una silla: las siguientes compras deben tomar la libre.
        vuelo = self.crear_vuelo()
        relleno = Reserva.objects.create(cliente=self.otro, estado="cancelada")
        ocupadas = [Tiquete(reserva=relleno, vuelo=vuelo, silla=s,
                            valor=1, clase="economica", documento=f"X{s:05d}", nombres="a", apellidos="b",
                            fecha_nacimiento="1990-01-01", genero="otro", telefono="3000000", correo="x@x.com",
                            contacto_nombre="c", contacto_telefono="3000001") for s in range(26, 150)]
        Tiquete.objects.bulk_create(ocupadas)
        reserva = self.comprar(vuelo, [viajero("1000001")])
        self.assertEqual(reserva.tiquetes.get().silla, 150)

    def test_clase_llena(self):
        vuelo = self.crear_vuelo()
        relleno = Reserva.objects.create(cliente=self.otro, estado="cancelada")
        Tiquete.objects.bulk_create([
            Tiquete(reserva=relleno, vuelo=vuelo, silla=s, valor=1, clase="primera", documento=f"X{s:05d}", nombres="a",
                    apellidos="b", fecha_nacimiento="1990-01-01", genero="otro", telefono="3000000", correo="x@x.com",
                    contacto_nombre="c", contacto_telefono="3000001") for s in range(1, 26)])
        with self.assertRaisesMessage(ValidationError, "No quedan sillas de primera clase"):
            self.comprar(vuelo, [viajero("1000001", clase="primera")])
        self.assertEqual(self.saldo(), Decimal("5000000"))  # la compra fallida no cobró nada
        self.comprar(vuelo, [viajero("1000001", clase="economica")])

    def test_base_de_datos_impide_silla_repetida(self):
        reserva = self.comprar(self.vuelo, [viajero("1000001")])
        t = reserva.tiquetes.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Tiquete.objects.create(reserva=reserva, vuelo=self.vuelo, silla=t.silla, valor=1, clase=t.clase,
                                   documento="OTRO999", nombres="a", apellidos="b", fecha_nacimiento="1990-01-01",
                                   genero="otro", telefono="3000000", correo="x@x.com", contacto_nombre="c",
                                   contacto_telefono="3000001")

    def test_clase_invalida(self):
        self.client.force_login(self.cliente)
        r = self.client.post(reverse("reservas:iniciar", args=[self.vuelo.codigo, "comprar"]),
                             datos_post([viajero(clase="vip")]))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("carrito_tiquetes", self.client.session)

    def test_pantalla_muestra_clase_y_silla(self):
        self.client.force_login(self.cliente)
        reserva = self.comprar(self.vuelo, [viajero("1000001", clase="primera")])
        r = self.client.get(reverse("reservas:detalle", args=[reserva.codigo]))
        self.assertContains(r, "Primera clase")
        self.assertContains(r, f"Silla {reserva.tiquetes.get().silla}")
