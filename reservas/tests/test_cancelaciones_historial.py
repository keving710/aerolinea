from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from finanzas.models import Movimiento
from reservas import servicios
from reservas.models import Reserva, Tiquete
from vuelos.models import Vuelo

from .base import BaseReservas, viajero


class Ayudas:
    def comprar(self, vuelo, viajeros, cliente=None, tarjeta=None, regreso=None):
        linea = {"vuelo": vuelo.codigo, "regreso": regreso.codigo if regreso else "", "viajeros": viajeros}
        return servicios.comprar(cliente or self.cliente, [linea], tarjeta or self.tarjeta)[0]

    def reservar(self, vuelo, viajeros, cliente=None):
        return servicios.reservar(cliente or self.cliente, {"vuelo": vuelo.codigo, "regreso": "", "viajeros": viajeros})

    def mover_salida(self, vuelo, delta):
        """Cambia la salida del vuelo sin pasar por save() (simula el paso del tiempo)."""
        salida = timezone.now() + delta
        Vuelo.objects.filter(pk=vuelo.pk).update(salida=salida, llegada=salida + timedelta(hours=1))
        vuelo.refresh_from_db()


class CancelacionClienteTests(Ayudas, BaseReservas):
    """HU 32."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.cliente)

    def test_cancelar_compra_reintegra_y_libera_cupos(self):
        reserva = self.comprar(self.vuelo, [viajero("1000001"), viajero("1000002")])
        self.assertEqual(self.saldo(), Decimal("4600000"))
        r = self.client.post(reverse("reservas:cancelar", args=[reserva.codigo]))
        self.assertRedirects(r, reverse("reservas:detalle", args=[reserva.codigo]))
        reserva.refresh_from_db()
        self.vuelo.refresh_from_db()
        self.assertEqual(reserva.estado, "cancelada")
        self.assertEqual((self.vuelo.tiquetes_vendidos, self.vuelo.cupos_disponibles), (0, 150))
        self.assertEqual(self.saldo(), Decimal("5000000"))
        m = Movimiento.objects.get(tipo="reembolso")
        self.assertEqual((m.valor, m.saldo_resultante, m.tarjeta_id), (Decimal("400000"), Decimal("5000000"), self.tarjeta.pk))
        self.assertFalse(reserva.tiquetes.filter(estado="activo").exists())
        # También se ve en el historial de la billetera.
        self.assertContains(self.client.get(reverse("finanzas:panel")), "Reembolso")

    def test_cancelacion_hasta_una_hora_antes(self):
        reserva = self.comprar(self.vuelo, [viajero("1000001")])
        self.mover_salida(self.vuelo, timedelta(minutes=61))
        self.assertEqual(servicios.motivo_no_cancelable(reserva), "")
        self.mover_salida(self.vuelo, timedelta(minutes=59))
        self.assertIn("1 hora antes", servicios.motivo_no_cancelable(reserva))
        r = self.client.post(reverse("reservas:cancelar", args=[reserva.codigo]), follow=True)
        self.assertContains(r, "hasta 1 hora antes")
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, "comprada")
        self.assertEqual(self.saldo(), Decimal("4800000"))
        self.assertFalse(Movimiento.objects.filter(tipo="reembolso").exists())

    def test_cancelar_reserva_dentro_de_24_horas(self):
        reserva = self.reservar(self.vuelo, [viajero("1000001")])
        self.client.post(reverse("reservas:cancelar", args=[reserva.codigo]))
        reserva.refresh_from_db()
        self.vuelo.refresh_from_db()
        self.assertEqual((reserva.estado, self.vuelo.cupos_reservados), ("cancelada", 0))
        self.assertFalse(Movimiento.objects.filter(tipo="reembolso").exists())

    def test_reserva_vencida_no_se_cancela(self):
        reserva = self.reservar(self.vuelo, [viajero("1000001")])
        Reserva.objects.filter(pk=reserva.pk).update(expira_en=timezone.now() - timedelta(minutes=1))
        r = self.client.post(reverse("reservas:cancelar", args=[reserva.codigo]), follow=True)
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, "vencida")
        self.assertContains(r, "ya está vencida")

    def test_no_se_cancela_dos_veces(self):
        reserva = self.comprar(self.vuelo, [viajero("1000001")])
        servicios.cancelar(self.cliente, reserva.pk)
        with self.assertRaisesMessage(ValidationError, "ya está cancelada"):
            servicios.cancelar(self.cliente, reserva.pk)
        self.assertEqual(self.saldo(), Decimal("5000000"))
        self.assertEqual(Movimiento.objects.filter(tipo="reembolso").count(), 1)

    def test_no_se_cancela_la_reserva_de_otro(self):
        reserva = self.comprar(self.vuelo, [viajero("1000001")])
        self.client.force_login(self.otro)
        self.assertEqual(self.client.post(reverse("reservas:cancelar", args=[reserva.codigo])).status_code, 404)
        self.assertEqual(self.client.get(reverse("reservas:detalle", args=[reserva.codigo])).status_code, 404)
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, "comprada")

    def test_cancelar_exige_post_y_rol_cliente(self):
        reserva = self.comprar(self.vuelo, [viajero("1000001")])
        self.assertEqual(self.client.get(reverse("reservas:cancelar", args=[reserva.codigo])).status_code, 405)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse("reservas:cancelar", args=[reserva.codigo])).status_code, 403)

    def test_se_puede_volver_a_comprar_el_mismo_asiento_y_viajero(self):
        reserva = self.comprar(self.vuelo, [viajero("1000001")])
        servicios.cancelar(self.cliente, reserva.pk)
        self.comprar(self.vuelo, [viajero("1000001")])  # el viajero ya no está duplicado
        self.assertEqual(Tiquete.objects.filter(estado="activo").count(), 1)

    def test_pagina_de_detalle_ofrece_cancelar_o_explica_el_motivo(self):
        reserva = self.comprar(self.vuelo, [viajero("1000001")])
        self.assertContains(self.client.get(reverse("reservas:detalle", args=[reserva.codigo])), "Cancelar compra")
        self.mover_salida(self.vuelo, timedelta(minutes=30))
        self.assertContains(self.client.get(reverse("reservas:detalle", args=[reserva.codigo])), "hasta 1 hora antes")


class HistorialTests(Ayudas, BaseReservas):
    """HU 33."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.cliente)

    def test_lista_compras_reservas_y_canceladas_con_estado(self):
        compra = self.comprar(self.vuelo, [viajero("1000001")])
        reserva = self.reservar(self.crear_vuelo(dias=12), [viajero("1000002")])
        cancelada = self.comprar(self.crear_vuelo(dias=13), [viajero("1000003")])
        servicios.cancelar(self.cliente, cancelada.pk)
        r = self.client.get(reverse("reservas:historial"))
        for reserva_ in (compra, reserva, cancelada):
            self.assertContains(r, reserva_.codigo)
        self.assertContains(r, "Comprada")
        self.assertContains(r, "Reservada")
        self.assertContains(r, "Cancelada")

    def test_refleja_estado_del_checkin(self):
        compra = self.comprar(self.vuelo, [viajero("1000001"), viajero("1000002")])
        self.assertContains(self.client.get(reverse("reservas:historial")), "Pendiente", count=2)
        Tiquete.objects.filter(reserva=compra, documento="1000001").update(checkin_completado=True)
        r = self.client.get(reverse("reservas:historial"))
        self.assertContains(r, "Completado", count=1)
        self.assertContains(r, "Pendiente", count=1)

    def test_filtra_por_estado_y_solo_muestra_las_propias(self):
        propia = self.comprar(self.vuelo, [viajero("1000001")])
        ajena = self.comprar(self.crear_vuelo(dias=12), [viajero("2000001")], cliente=self.otro,
                             tarjeta=self.tarjeta_con_saldo(self.otro, 5_000_000, numero="5555555555554444"))
        r = self.client.get(reverse("reservas:historial"))
        self.assertContains(r, propia.codigo)
        self.assertNotContains(r, ajena.codigo)
        self.assertNotContains(self.client.get(reverse("reservas:historial") + "?estado=reservada"), propia.codigo)
        self.assertContains(self.client.get(reverse("reservas:historial") + "?estado=comprada"), propia.codigo)

    def test_historial_vacio_y_solo_para_clientes(self):
        self.assertContains(self.client.get(reverse("reservas:historial")), "Aún no tienes compras ni reservas")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("reservas:historial")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("reservas:historial")).status_code, 302)

    def test_reservas_vencidas_aparecen_como_vencidas(self):
        reserva = self.reservar(self.vuelo, [viajero("1000001")])
        Reserva.objects.filter(pk=reserva.pk).update(expira_en=timezone.now() - timedelta(minutes=1))
        self.assertContains(self.client.get(reverse("reservas:historial")), "Vencida")


class PromocionTests(Ayudas, BaseReservas):
    """HU 16."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.url = reverse("vuelos:promocion", args=[self.vuelo.codigo])

    def aplicar(self, descuento):
        return self.client.post(self.url, {"descuento": descuento})

    def test_promocion_cambia_el_valor_de_los_cupos_disponibles(self):
        self.assertEqual(self.aplicar("25").status_code, 302)
        self.vuelo.refresh_from_db()
        self.assertEqual((self.vuelo.costo_persona, self.vuelo.descuento_porcentaje, self.vuelo.costo_vigente),
                         (Decimal("200000"), Decimal("25"), Decimal("150000")))
        self.assertContains(self.client.get(reverse("vuelos:publico", args=[self.vuelo.codigo])), "150.000")

    def test_se_permite_aunque_haya_tiquetes_vendidos_y_estos_conservan_su_valor(self):
        vendida = self.comprar(self.vuelo, [viajero("1000001")])
        reservada = self.reservar(self.vuelo, [viajero("1000002")])
        self.assertEqual(self.client.get(reverse("vuelos:editar", args=[self.vuelo.codigo])).status_code, 409)  # HU 15
        self.assertEqual(self.aplicar("50").status_code, 302)
        nueva = self.comprar(self.vuelo, [viajero("1000003")])
        self.assertEqual(vendida.tiquetes.get().valor, Decimal("200000"))
        self.assertEqual(reservada.tiquetes.get().valor, Decimal("200000"))
        self.assertEqual(nueva.tiquetes.get().valor, Decimal("100000"))
        self.assertEqual(self.saldo(), Decimal("4700000"))

    def test_reintegro_devuelve_lo_que_se_pago_y_no_el_valor_promocional(self):
        vendida = self.comprar(self.vuelo, [viajero("1000001")])
        self.aplicar("50")
        servicios.cancelar(self.cliente, vendida.pk)
        self.assertEqual(self.saldo(), Decimal("5000000"))

    def test_quitar_la_promocion(self):
        self.aplicar("40")
        self.aplicar("0")
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.costo_vigente, Decimal("200000"))

    def test_porcentajes_invalidos(self):
        for valor in ("-1", "91", "100", "abc", ""):
            with self.subTest(valor=valor):
                self.assertEqual(self.aplicar(valor).status_code, 200)
                self.vuelo.refresh_from_db()
                self.assertEqual(self.vuelo.descuento_porcentaje, 0)

    def test_redondeo_a_pesos(self):
        self.aplicar("33.33")
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.costo_vigente, Decimal("133340.00"))
        self.aplicar("90")
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.costo_vigente, Decimal("20000.00"))

    def test_solo_el_administrador(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.aplicar("10").status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.aplicar("10").status_code, 403)
        self.client.logout()
        self.assertEqual(self.aplicar("10").status_code, 302)
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.descuento_porcentaje, 0)

    def test_no_aplica_a_vuelos_cancelados_o_pasados(self):
        Vuelo.objects.filter(pk=self.vuelo.pk).update(estado="cancelado")
        self.assertContains(self.aplicar("10"), "ya fue cancelado", status_code=409)
        Vuelo.objects.filter(pk=self.vuelo.pk).update(estado="programado")
        self.mover_salida(self.vuelo, timedelta(minutes=-5))
        self.assertContains(self.aplicar("10"), "ya se realizó", status_code=409)

    def test_sin_cupos_no_hay_a_quien_aplicar(self):
        Vuelo.objects.filter(pk=self.vuelo.pk).update(tiquetes_vendidos=150)
        self.assertContains(self.aplicar("10"), "no tiene cupos disponibles")
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.descuento_porcentaje, 0)

    def test_busqueda_usa_el_valor_vigente(self):
        otro = self.crear_vuelo(dias=11, costo="180000")
        self.aplicar("25")  # 200.000 -> 150.000
        r = self.client.get(reverse("vuelos:busqueda"), {"costo_max": "160000"})
        self.assertEqual([v.codigo for v in r.context["page_obj"]], [self.vuelo.codigo])
        r = self.client.get(reverse("vuelos:busqueda"), {"orden": "costo_persona"})
        self.assertEqual([v.codigo for v in r.context["page_obj"]], [self.vuelo.codigo, otro.codigo])
        self.assertContains(r, "-25%")

    def test_editar_el_costo_base_conserva_la_promocion(self):
        self.aplicar("50")
        self.vuelo.refresh_from_db()
        self.vuelo.costo_persona = Decimal("300000")
        self.vuelo.save(update_fields=["costo_persona"])
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.costo_vigente, Decimal("150000"))

    def test_pantalla_muestra_resumen(self):
        self.comprar(self.vuelo, [viajero("1000001")])
        r = self.client.get(self.url)
        self.assertContains(r, "conservan el valor con el que se emitieron")


class CancelarVueloTests(Ayudas, BaseReservas):
    """HU 17."""

    def setUp(self):
        super().setUp()
        self.alt = self.crear_vuelo(dias=11)
        self.tarjeta_otro = self.tarjeta_con_saldo(self.otro, 5_000_000, numero="5555555555554444")
        self.client.force_login(self.admin)

    def cancelar(self, vuelo=None, confirmar=True):
        return self.client.post(reverse("vuelos:cancelar", args=[(vuelo or self.vuelo).codigo]), {"confirmar": "on"} if confirmar else {})

    def test_reubica_en_vuelo_de_otra_fecha_y_hora(self):
        compra = self.comprar(self.vuelo, [viajero("1000001", clase="primera"), viajero("1000002")])
        reserva = self.reservar(self.vuelo, [viajero("2000001")], cliente=self.otro)
        r = self.cancelar()
        self.assertRedirects(r, reverse("vuelos:detalle", args=[self.vuelo.codigo]))
        self.vuelo.refresh_from_db()
        self.alt.refresh_from_db()
        self.assertEqual(self.vuelo.estado, "cancelado")
        self.assertEqual((self.vuelo.tiquetes_vendidos, self.vuelo.cupos_reservados), (0, 0))
        self.assertEqual((self.alt.tiquetes_vendidos, self.alt.cupos_reservados), (2, 1))
        sillas = {t.documento: t for t in Tiquete.objects.filter(estado="activo")}
        self.assertTrue(all(t.vuelo_id == self.alt.pk and t.reubicado_desde_id == self.vuelo.pk for t in sillas.values()))
        self.assertTrue(1 <= sillas["1000001"].silla <= 25)  # conserva la clase
        self.assertTrue(26 <= sillas["1000002"].silla <= 150)
        self.assertEqual(self.saldo(), Decimal("4600000"))  # sin reintegro: viaja en el otro vuelo
        self.assertFalse(Movimiento.objects.filter(tipo="reembolso").exists())
        compra.refresh_from_db()
        reserva.refresh_from_db()
        self.assertEqual((compra.estado, reserva.estado), ("comprada", "reservada"))

    def test_sin_alternativa_reintegra_a_la_tarjeta_y_registra_movimiento(self):
        Vuelo.objects.filter(pk=self.alt.pk).delete()
        compra = self.comprar(self.vuelo, [viajero("1000001"), viajero("1000002")])
        reserva = self.reservar(self.vuelo, [viajero("2000001")], cliente=self.otro)
        self.cancelar()
        self.assertEqual(self.saldo(), Decimal("5000000"))
        m = Movimiento.objects.get(tipo="reembolso")
        self.assertEqual((m.valor, m.tarjeta_id, m.saldo_resultante), (Decimal("400000"), self.tarjeta.pk, Decimal("5000000")))
        self.assertIn(self.vuelo.codigo, m.detalle)
        compra.refresh_from_db()
        reserva.refresh_from_db()
        self.assertEqual((compra.estado, reserva.estado), ("cancelada", "cancelada"))
        self.assertEqual(self.saldo(self.tarjeta_otro), Decimal("5000000"))  # la reserva nunca se pagó
        self.vuelo.refresh_from_db()
        self.assertEqual((self.vuelo.tiquetes_vendidos, self.vuelo.cupos_reservados), (0, 0))

    def test_el_vuelo_cancelado_deja_de_aparecer_en_busquedas(self):
        self.client.logout()
        self.assertContains(self.client.get(reverse("vuelos:busqueda")), self.vuelo.codigo)
        self.client.force_login(self.admin)
        self.cancelar()
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("vuelos:busqueda")), self.vuelo.codigo)
        self.assertEqual(self.client.get(reverse("vuelos:publico", args=[self.vuelo.codigo])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("inicio")), self.vuelo.codigo)

    def test_no_reubica_si_la_alternativa_no_tiene_cupos_para_todo_el_grupo(self):
        Vuelo.objects.filter(pk=self.alt.pk).update(tiquetes_vendidos=149)
        self.comprar(self.vuelo, [viajero("1000001"), viajero("1000002")])
        self.cancelar()
        self.assertEqual(self.saldo(), Decimal("5000000"))
        self.assertFalse(Tiquete.objects.filter(estado="activo").exists())

    def test_prueba_la_siguiente_alternativa(self):
        Vuelo.objects.filter(pk=self.alt.pk).update(tiquetes_vendidos=149)
        lejana = self.crear_vuelo(dias=14)
        self.comprar(self.vuelo, [viajero("1000001"), viajero("1000002")])
        self.cancelar()
        self.assertEqual({t.vuelo_id for t in Tiquete.objects.filter(estado="activo")}, {lejana.pk})

    def test_elige_la_alternativa_mas_cercana_y_nunca_la_misma_hora(self):
        mismo_horario = self.crear_vuelo(dias=10)
        Vuelo.objects.filter(pk=mismo_horario.pk).update(salida=self.vuelo.salida, llegada=self.vuelo.llegada)
        cercana = self.crear_vuelo(dias=9)
        self.comprar(self.vuelo, [viajero("1000001")])
        self.cancelar()
        self.assertEqual(Tiquete.objects.get(estado="activo").vuelo_id, cercana.pk)

    def test_no_reubica_en_otra_ruta_ni_tipo(self):
        self.crear_vuelo(dias=11, destino="Cali")
        Vuelo.objects.filter(pk=self.alt.pk).delete()
        self.comprar(self.vuelo, [viajero("1000001")])
        self.cancelar()
        self.assertEqual(self.saldo(), Decimal("5000000"))

    def test_respeta_viajero_unico_y_limite_por_vuelo_en_el_destino(self):
        self.comprar(self.alt, [viajero("1000001")], cliente=self.otro, tarjeta=self.tarjeta_otro)  # mismo viajero en la alternativa
        self.comprar(self.vuelo, [viajero("1000001")])
        self.cancelar()
        self.assertEqual(self.saldo(), Decimal("5000000"))  # reintegro, no pudo reubicar

    def test_ida_y_vuelta_no_se_reubica_si_el_regreso_queda_antes(self):
        regreso = self.crear_vuelo(dias=10, horas=5, origen="Bogotá", destino="Pereira", costo="100000")
        # La ida alternativa llega después de la salida del regreso: no sirve.
        Vuelo.objects.filter(pk=self.alt.pk).update(salida=regreso.salida + timedelta(hours=1), llegada=regreso.salida + timedelta(hours=2))
        compra = self.comprar(self.vuelo, [viajero("1000001")], regreso=regreso)
        self.assertEqual(self.saldo(), Decimal("4700000"))
        self.cancelar()
        self.assertEqual(self.saldo(), Decimal("4900000"))  # solo se reintegra la ida (200.000)
        compra.refresh_from_db()
        self.assertEqual(compra.estado, "comprada")
        self.assertEqual(list(compra.tiquetes.filter(estado="activo").values_list("vuelo__codigo", flat=True)), [regreso.codigo])
        # Si luego el cliente cancela, solo se devuelve lo que sigue vigente.
        servicios.cancelar(self.cliente, compra.pk)
        self.assertEqual(self.saldo(), Decimal("5000000"))

    def test_cada_pasajero_queda_reubicado_o_reintegrado(self):
        for i in range(4):
            self.comprar(self.vuelo, [viajero(str(1000000 + i))], cliente=self.cliente)
            if i == 1:
                Vuelo.objects.filter(pk=self.alt.pk).update(tiquetes_vendidos=149)
        self.cancelar()
        self.assertFalse(Tiquete.objects.filter(vuelo=self.vuelo, estado="activo").exists())
        reubicados = Tiquete.objects.filter(estado="activo").count()
        reintegrados = Tiquete.objects.filter(estado="cancelado").count()
        self.assertEqual(reubicados + reintegrados, 4)
        self.assertEqual(self.saldo(), Decimal("5000000") - Decimal("200000") * reubicados)

    def test_informa_por_correo_a_los_viajeros(self):
        self.comprar(self.vuelo, [viajero("1000001", correo="uno@correo.com")])
        mail.outbox.clear()
        self.cancelar()
        self.assertEqual([m.to[0] for m in mail.outbox], ["uno@correo.com"])
        self.assertIn("fue cancelado", mail.outbox[0].body)
        self.assertIn(self.alt.codigo, mail.outbox[0].body)

    def test_exige_confirmacion(self):
        self.assertEqual(self.cancelar(confirmar=False).status_code, 200)
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.estado, "programado")

    def test_solo_administrador(self):
        for usuario in (self.cliente, self.root):
            self.client.force_login(usuario)
            self.assertEqual(self.cancelar().status_code, 403)
        self.client.logout()
        self.assertEqual(self.cancelar().status_code, 302)
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.estado, "programado")
        with self.assertRaises(Exception):
            servicios.cancelar_vuelo(self.cliente, self.vuelo.pk)

    def test_no_se_cancela_dos_veces_ni_un_vuelo_realizado(self):
        self.comprar(self.vuelo, [viajero("1000001")])
        self.cancelar()
        self.assertContains(self.cancelar(), "ya fue cancelado", status_code=409)
        self.assertEqual(Movimiento.objects.filter(tipo="reembolso").count(), 0)
        self.mover_salida(self.alt, timedelta(minutes=-5))
        self.assertContains(self.cancelar(self.alt), "ya se realizó", status_code=409)

    def test_vuelo_sin_tiquetes(self):
        self.assertEqual(self.cancelar().status_code, 302)
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.estado, "cancelado")

    def test_aparece_en_la_categoria_de_cancelados(self):
        self.cancelar()
        self.assertContains(self.client.get(reverse("vuelos:cancelados")), self.vuelo.codigo)
        self.assertNotContains(self.client.get(reverse("vuelos:lista")), self.vuelo.codigo)

    def test_pantalla_de_confirmacion_resume_el_impacto(self):
        self.comprar(self.vuelo, [viajero("1000001")])
        r = self.client.get(reverse("vuelos:cancelar", args=[self.vuelo.codigo]))
        self.assertContains(r, self.alt.codigo)
        self.assertEqual(r.context["comprados"], 1)


class VuelosRealizadosTests(Ayudas, BaseReservas):
    """HU 18."""

    def test_pasada_la_fecha_el_vuelo_pasa_a_realizado(self):
        self.mover_salida(self.vuelo, timedelta(minutes=-1))
        self.assertEqual(servicios.marcar_realizados(), 1)
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.estado, "realizado")
        self.assertEqual(servicios.marcar_realizados(), 0)

    def test_no_marca_vuelos_futuros(self):
        self.assertEqual(servicios.marcar_realizados(), 0)
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.estado, "programado")

    def test_aparece_en_realizados_y_deja_de_estar_disponible(self):
        self.mover_salida(self.vuelo, timedelta(minutes=-1))
        servicios.marcar_realizados()
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("vuelos:realizados")), self.vuelo.codigo)
        self.assertNotContains(self.client.get(reverse("vuelos:lista")), self.vuelo.codigo)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("vuelos:busqueda")), self.vuelo.codigo)

    def test_se_registra_solo_al_entrar_a_la_lista_del_administrador(self):
        self.mover_salida(self.vuelo, timedelta(minutes=-1))
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("vuelos:realizados")), self.vuelo.codigo)
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.estado, "realizado")

    def test_middleware_marca_realizados_sin_intervencion(self):
        from reservas import middleware
        self.mover_salida(self.vuelo, timedelta(minutes=-1))
        middleware._ultimo = 0.0
        self.client.get(reverse("vuelos:busqueda"))
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.estado, "realizado")

    def test_la_compra_realizada_se_conserva_en_el_historial(self):
        compra = self.comprar(self.vuelo, [viajero("1000001")])
        self.mover_salida(self.vuelo, timedelta(minutes=-1))
        servicios.mantenimiento()
        compra.refresh_from_db()
        self.assertEqual(compra.estado, "comprada")
        self.client.force_login(self.cliente)
        self.assertContains(self.client.get(reverse("reservas:historial")), compra.codigo)
        self.assertIn("1 hora antes", servicios.motivo_no_cancelable(compra))

    def test_reservas_sin_pagar_de_un_vuelo_realizado_se_liberan(self):
        reserva = self.reservar(self.vuelo, [viajero("1000001")])
        salida = timezone.now() - timedelta(minutes=1)
        Vuelo.objects.filter(pk=self.vuelo.pk).update(salida=salida, llegada=salida + timedelta(hours=1))
        Reserva.objects.filter(pk=reserva.pk).update(expira_en=salida)
        resultado = servicios.mantenimiento()
        self.assertEqual(resultado, {"realizados": 1, "liberadas": 1})
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, "vencida")

    def test_comando_de_mantenimiento(self):
        from io import StringIO
        from django.core.management import call_command
        self.mover_salida(self.vuelo, timedelta(minutes=-1))
        salida = StringIO()
        call_command("mantener_reservas", stdout=salida)
        self.assertIn("realizados: 1", salida.getvalue())
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.estado, "realizado")

    def test_solo_el_administrador_ve_los_realizados(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.get(reverse("vuelos:realizados")).status_code, 403)
