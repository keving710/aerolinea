import uuid
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.test import Client, TestCase
from django.urls import reverse

from usuarios.models import Usuario
from . import services
from .models import Movimiento, Tarjeta


class FinanzasTests(TestCase):
    def setUp(self):
        self.ana = Usuario.objects.create_user("ana", rol="cliente")
        self.luz = Usuario.objects.create_user("luz", rol="cliente")
        self.admin = Usuario.objects.create_user("adm", rol="administrador")
        self.tarjeta = services.registrar_tarjeta(self.ana, "4111 1111 1111 1111", "debito", "100.00")
        self.otra = services.registrar_tarjeta(self.luz, "5555555555554444", "credito", "900")
        self.client.force_login(self.ana)

    def test_panel_individual_y_privado(self):
        response = self.client.get(reverse("finanzas:panel"))
        self.assertContains(response, "1111")
        self.assertNotContains(response, "4444")
        self.assertNotContains(response, "4111111111111111")
        self.assertEqual(response.context["saldo_total"], Decimal("100"))
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_solo_cliente_en_todas_las_rutas(self):
        for nombre in ("panel", "nueva_tarjeta", "recargar", "simular_pago"):
            ruta = reverse("finanzas:" + nombre)
            self.client.logout()
            self.assertEqual(self.client.get(ruta).status_code, 302)
            for usuario in (self.admin, Usuario.objects.get(rol="root")):
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(ruta).status_code, 403)
                self.assertEqual(self.client.post(ruta, {}).status_code, 403)

    def test_tarjeta_nunca_conserva_numero_completo(self):
        self.assertEqual(self.tarjeta.ultimos_cuatro, "1111")
        self.assertEqual(len(self.tarjeta.huella), 64)
        self.assertNotIn("4111111111111111", str(self.tarjeta.__dict__))
        self.assertEqual(self.tarjeta.movimientos.get().tipo, "recarga")

    def test_duplicada_normalizada_y_saldo_cero(self):
        with self.assertRaises(ValidationError):
            services.registrar_tarjeta(self.ana, "4111-1111-1111-1111", "credito", "100")
        cero = services.registrar_tarjeta(self.ana, "4000000000000002", "credito", 0)
        self.assertEqual(cero.saldo, 0)
        self.assertFalse(cero.movimientos.exists())

    def test_validacion_backend_tarjetas(self):
        for numero, tipo, saldo in [("abc", "debito", 0), ("４" * 16, "debito", 0),
                                   ("4000000000000002", "otro", 0), ("4000000000000002", "debito", -1)]:
            with self.subTest(numero=numero, tipo=tipo, saldo=saldo), self.assertRaises(ValidationError):
                services.registrar_tarjeta(self.ana, numero, tipo, saldo)
        with self.assertRaises(PermissionDenied):
            services.registrar_tarjeta(self.admin, "4000000000000002", "credito", 0)

    def test_recarga_suma_y_registra_saldo_resultante(self):
        m = services.recargar(self.ana, self.tarjeta.pk, "25.75", uuid.uuid4())
        self.tarjeta.refresh_from_db()
        self.assertEqual(self.tarjeta.saldo, Decimal("125.75"))
        self.assertEqual(m.valor, Decimal("25.75"))
        self.assertEqual(m.saldo_resultante, self.tarjeta.saldo)

    def test_pago_solo_descuenta_tarjeta_elegida_y_reembolso(self):
        segunda = services.registrar_tarjeta(self.ana, "4000000000000002", "credito", "200")
        m = services.cobrar(self.ana, segunda.pk, "60.50", uuid.uuid4())
        self.assertEqual(m.saldo_resultante, Decimal("139.50"))
        self.tarjeta.refresh_from_db()
        self.assertEqual(self.tarjeta.saldo, Decimal("100"))
        r = services.reembolsar(self.ana, segunda.pk, "60.50", uuid.uuid4())
        self.assertEqual(r.saldo_resultante, Decimal("200"))
        self.assertEqual(list(segunda.movimientos.values_list("tipo", flat=True)), ["reembolso", "compra", "recarga"])

    def test_insuficiente_no_deja_movimiento_ni_saldo_negativo(self):
        antes = Movimiento.objects.count()
        with self.assertRaisesMessage(ValidationError, "No tienes saldo disponible"):
            services.cobrar(self.ana, self.tarjeta.pk, "100.01", uuid.uuid4())
        self.tarjeta.refresh_from_db()
        self.assertEqual(self.tarjeta.saldo, Decimal("100"))
        self.assertEqual(Movimiento.objects.count(), antes)
        services.cobrar(self.ana, self.tarjeta.pk, "100", uuid.uuid4())
        self.tarjeta.refresh_from_db()
        self.assertEqual(self.tarjeta.saldo, 0)

    def test_importes_invalidos_no_mutan(self):
        for valor in ("NaN", "Infinity", "-1", "0", "0.001", "1000000000000", "abc"):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                services.recargar(self.ana, self.tarjeta.pk, valor, uuid.uuid4())
        self.tarjeta.refresh_from_db()
        self.assertEqual(self.tarjeta.saldo, 100)

    def test_desbordamiento_revierte_operacion(self):
        with self.assertRaises(ValidationError):
            services.recargar(self.ana, self.tarjeta.pk, services.MAX_SALDO, uuid.uuid4())
        self.tarjeta.refresh_from_db()
        self.assertEqual(self.tarjeta.saldo, 100)

    def test_servicios_no_acceden_tarjetas_ajenas(self):
        for servicio in (services.recargar, services.cobrar, services.reembolsar):
            with self.assertRaises(Http404):
                servicio(self.ana, self.otra.pk, "1", uuid.uuid4())
            with self.assertRaises(PermissionDenied):
                servicio(self.admin, self.tarjeta.pk, "1", uuid.uuid4())

    def test_reintento_idempotente_y_referencia_no_reutilizable(self):
        referencia = uuid.uuid4()
        uno = services.cobrar(self.ana, self.tarjeta.pk, "10", referencia)
        dos = services.cobrar(self.ana, self.tarjeta.pk, "10", referencia)
        self.assertEqual(uno.pk, dos.pk)
        with self.assertRaises(ValidationError):
            services.cobrar(self.ana, self.tarjeta.pk, "11", referencia)
        self.tarjeta.refresh_from_db()
        self.assertEqual(self.tarjeta.saldo, 90)

    def test_rollback_incluye_historial(self):
        antes = Movimiento.objects.count()
        try:
            with transaction.atomic():
                services.cobrar(self.ana, self.tarjeta.pk, "50", uuid.uuid4())
                raise RuntimeError("Falla de futura confirmación de tiquetes")
        except RuntimeError:
            pass
        self.tarjeta.refresh_from_db()
        self.assertEqual(self.tarjeta.saldo, 100)
        self.assertEqual(Movimiento.objects.count(), antes)

    def test_fallo_de_historial_revierte_saldo(self):
        from unittest.mock import patch
        with patch("finanzas.services.Movimiento.objects.create", side_effect=RuntimeError("BD")):
            with self.assertRaises(RuntimeError):
                services.recargar(self.ana, self.tarjeta.pk, "25", uuid.uuid4())
        self.tarjeta.refresh_from_db()
        self.assertEqual(self.tarjeta.saldo, 100)

    def test_segundo_pago_revalida_saldo_actual(self):
        services.cobrar(self.ana, self.tarjeta.pk, "80", uuid.uuid4())
        with self.assertRaises(ValidationError):
            services.cobrar(self.ana, self.tarjeta.pk, "80", uuid.uuid4())
        self.tarjeta.refresh_from_db()
        self.assertEqual(self.tarjeta.saldo, 20)

    def test_referencia_invalida_y_conflicto_entre_tarjetas(self):
        with self.assertRaises(ValidationError):
            services.recargar(self.ana, self.tarjeta.pk, "1", "no-es-uuid")
        ref = uuid.uuid4()
        services.recargar(self.ana, self.tarjeta.pk, "1", ref)
        with self.assertRaises(ValidationError):
            services.recargar(self.luz, self.otra.pk, "1", ref)

    def test_pagina_formulario_oculta_referencia_y_numero_en_error(self):
        response = self.client.get(reverse("finanzas:recargar"))
        self.assertContains(response, 'type="hidden" name="referencia"')
        self.assertNotContains(response, 'for="id_referencia"')
        response = self.client.post(reverse("finanzas:nueva_tarjeta"), {
            "numero": "4000000000000002", "tipo": "credito", "saldo": "-1"})
        self.assertNotContains(response, "4000000000000002")
        self.assertContains(response, 'aria-invalid="true"')

    def test_post_ajeno_no_muta_y_muestra_error(self):
        for ruta in ("recargar", "simular_pago"):
            r = self.client.post(reverse("finanzas:" + ruta), {
                "tarjeta": self.otra.pk, "valor": "50", "referencia": uuid.uuid4()})
            self.assertEqual(r.status_code, 200)
            self.assertIn("tarjeta", r.context["form"].errors)
        self.otra.refresh_from_db()
        self.assertEqual(self.otra.saldo, 900)

    def test_pago_http_insuficiente_seleccion_y_reenvio(self):
        ruta = reverse("finanzas:simular_pago")
        data = {"tarjeta": self.tarjeta.pk, "valor": "101", "referencia": uuid.uuid4()}
        self.assertContains(self.client.post(ruta, data), "No tienes saldo disponible")
        data.update(valor="10", referencia=uuid.uuid4())
        for _ in range(2):
            self.assertRedirects(self.client.post(ruta, data), reverse("finanzas:panel"))
        self.tarjeta.refresh_from_db()
        self.assertEqual(self.tarjeta.saldo, 90)

    def test_registro_http_saldo_propietario_no_manipulable(self):
        r = self.client.post(reverse("finanzas:nueva_tarjeta"), {"numero": "4000000000000002",
            "tipo": "credito", "saldo": "40.50", "cliente": self.luz.pk})
        self.assertRedirects(r, reverse("finanzas:panel"))
        self.assertEqual(Tarjeta.objects.get(ultimos_cuatro="0002").cliente, self.ana)

    def test_csrf_y_get_no_tienen_efectos(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.ana)
        antes = Movimiento.objects.count()
        for nombre in ("recargar", "simular_pago", "nueva_tarjeta"):
            ruta = reverse("finanzas:" + nombre)
            self.assertEqual(client.post(ruta, {}).status_code, 403)
            self.assertEqual(client.get(ruta).status_code, 200)
        self.assertEqual(Movimiento.objects.count(), antes)

    def test_restricciones_bd_y_paginacion_aislada(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Tarjeta.objects.filter(pk=self.tarjeta.pk).update(saldo=-1)
        for _ in range(16):
            services.recargar(self.ana, self.tarjeta.pk, "1", uuid.uuid4())
        r = self.client.get(reverse("finanzas:panel"), {"page": "2"})
        self.assertEqual(len(r.context["page_obj"]), 2)
        self.assertNotContains(r, "4444")
