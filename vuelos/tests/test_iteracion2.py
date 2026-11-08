from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.models import Usuario
from vuelos.catalogo import buscar
from vuelos.models import Vuelo


class Iteracion2Tests(TestCase):
    def setUp(self):
        self.admin = Usuario.objects.create_user("admin2", rol="administrador")
        self.cliente = Usuario.objects.create_user("cliente2", rol="cliente")
        self.fecha = timezone.localdate() + timedelta(days=30)
        self.client.force_login(self.admin)
        self.client.post(reverse("vuelos:nuevo_nacional"), {"origen": "Pereira", "destino": "Bogotá",
                         "fecha": self.fecha, "hora_salida": "08:00", "hora_llegada": "09:00", "costo_persona": "250000"})
        self.vuelo = Vuelo.objects.get()

    def datos(self, **extra):
        data = {"origen": "Pereira", "destino": "Cali", "fecha": self.fecha, "hora_salida": "10:00",
                "hora_llegada": "11:20", "costo_persona": "280000"}
        data.update(extra)
        return data

    def editar(self, **extra):
        return self.client.post(reverse("vuelos:editar", args=[self.vuelo.codigo]), self.datos(**extra))

    def test_editar_preserva_identidad_y_recalcula_horario(self):
        self.assertEqual(self.editar(codigo="ATAQUE", tipo="internacional", capacidad=999).status_code, 302)
        self.vuelo.refresh_from_db()
        self.assertEqual((self.vuelo.codigo, self.vuelo.tipo, self.vuelo.capacidad), ("VU-00001", "nacional", 150))
        self.assertEqual(self.vuelo.destino, "Cali")
        self.assertEqual(self.vuelo.duracion_minutos, 80)
        self.assertEqual(self.vuelo.costo_persona, Decimal("280000"))
        self.assertContains(self.client.get(reverse("inicio")), "Cali")

    def test_edicion_validacion_mismos_criterios_iteracion1(self):
        for extra in ({"destino": "Pereira"}, {"origen": "Tokio"}, {"costo_persona": -1},
                      {"fecha": self.fecha - timedelta(days=100)}, {"hora_llegada": "10:00"}):
            with self.subTest(extra=extra):
                self.assertEqual(self.editar(**extra).status_code, 200)
                self.vuelo.refresh_from_db()
                self.assertEqual(self.vuelo.destino, "Bogotá")

    def test_edicion_bloquea_ventas_realizados_cancelados_pasados(self):
        for attrs, mensaje in [({"tiquetes_vendidos": 1}, "tiquetes vendidos"),
                               ({"estado": "realizado"}, "ya se realizó"),
                               ({"estado": "cancelado"}, "Solo se pueden editar"),
                               ({"salida": timezone.now() - timedelta(minutes=1)}, "ya se realizó")]:
            with self.subTest(attrs=attrs):
                Vuelo.objects.filter(pk=self.vuelo.pk).update(**attrs)
                self.assertContains(self.editar(), mensaje, status_code=409)
                self.vuelo.refresh_from_db()
                self.assertEqual(self.vuelo.destino, "Bogotá")
                Vuelo.objects.filter(pk=self.vuelo.pk).update(tiquetes_vendidos=0, estado="programado",
                    salida=timezone.now() + timedelta(days=29))

    def test_solo_admin_edita_get_y_post(self):
        ruta = reverse("vuelos:editar", args=[self.vuelo.codigo])
        self.client.logout()
        self.assertEqual(self.client.get(ruta).status_code, 302)
        for usuario in (self.cliente, Usuario.objects.get(rol="root")):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(ruta).status_code, 403)
            self.assertEqual(self.client.post(ruta, self.datos()).status_code, 403)

    def test_csrf_edicion(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.admin)
        self.assertEqual(c.post(reverse("vuelos:editar", args=[self.vuelo.codigo]), self.datos()).status_code, 403)

    def test_portada_publica_imagen_datos_y_detalle_sin_exponer_creador(self):
        self.client.logout()
        r = self.client.get(reverse("inicio"))
        for texto in ("VU-00001", "Pereira", "Bogotá", "08:00", "09:00", "150", "vuelo-nacional.svg", "1 h 00 min"):
            self.assertContains(r, texto)
        r = self.client.get(reverse("vuelos:publico", args=[self.vuelo.codigo]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "admin2")
        self.assertNotContains(r, "Editar vuelo")

    def test_busqueda_combinada_y_cada_criterio_independiente(self):
        filtros = {"codigo": "00001", "origen": "Pereira", "destino": "Bogotá", "tipo": "nacional",
                   "fecha": self.fecha, "hora": "08:00", "duracion_min": 60, "duracion_max": 60,
                   "costo_min": "250000", "costo_max": "250000"}
        self.client.logout()
        for data in [filtros] + [{k: v} for k, v in filtros.items()]:
            with self.subTest(data=data):
                r = self.client.get(reverse("vuelos:busqueda"), data)
                self.assertContains(r, "VU-00001")
                self.assertEqual(r.context["page_obj"].paginator.count, 1)
        self.client.force_login(self.cliente)
        self.assertContains(self.client.get(reverse("vuelos:busqueda"), filtros), "VU-00001")

    def test_busqueda_criterios_no_coincidentes(self):
        for data in ({"origen": "Cali"}, {"costo_max": "10"}, {"duracion_min": 61}, {"hora": "09:00"}):
            self.assertEqual(self.client.get(reverse("vuelos:busqueda"), data).context["page_obj"].paginator.count, 0)

    def test_busqueda_invalida_no_devuelve_todo(self):
        for data in ({"fecha": "no"}, {"costo_max": "NaN"}, {"tipo": "ataque"}, {"orden": "-creado_por"},
                     {"duracion_min": -1}, {"costo_min": 100, "costo_max": 1}, {"duracion_min": 90, "duracion_max": 10}):
            with self.subTest(data=data):
                r = self.client.get(reverse("vuelos:busqueda"), data)
                self.assertTrue(r.context["form"].errors)
                self.assertEqual(r.context["page_obj"].paginator.count, 0)

    def test_todos_los_canales_excluyen_no_disponibles(self):
        self.client.logout()
        for attrs in ({"estado": "cancelado"}, {"estado": "realizado"}, {"tiquetes_vendidos": 150},
                      {"cupos_reservados": 150}, {"salida": timezone.now() - timedelta(minutes=1)}):
            with self.subTest(attrs=attrs):
                Vuelo.objects.filter(pk=self.vuelo.pk).update(**attrs)
                self.assertNotContains(self.client.get(reverse("inicio")), "VU-00001")
                self.assertEqual(self.client.get(reverse("vuelos:busqueda")).context["page_obj"].paginator.count, 0)
                self.assertEqual(self.client.get(reverse("vuelos:publico", args=[self.vuelo.codigo])).status_code, 404)
                Vuelo.objects.filter(pk=self.vuelo.pk).update(estado="programado", tiquetes_vendidos=0,
                    cupos_reservados=0, salida=timezone.now() + timedelta(days=29))

    def test_cupos_restan_vendidos_y_reservados_y_bd_impide_sobreocupacion(self):
        Vuelo.objects.filter(pk=self.vuelo.pk).update(tiquetes_vendidos=20, cupos_reservados=10)
        self.vuelo.refresh_from_db()
        self.assertEqual(self.vuelo.cupos_disponibles, 120)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Vuelo.objects.filter(pk=self.vuelo.pk).update(tiquetes_vendidos=151)

    def test_busqueda_regreso_fecha_hora_zona_origen_y_dst(self):
        regreso = Vuelo.objects.create(tipo="internacional", origen="Madrid", destino="Bogotá",
            salida=datetime(2027, 7, 16, 0, 30, tzinfo=dt_timezone.utc),
            llegada=datetime(2027, 7, 16, 10, 30, tzinfo=dt_timezone.utc),
            duracion_minutos=600, costo_persona=3500000, capacidad=250, creado_por=self.admin)
        r = self.client.get(reverse("vuelos:busqueda"), {"origen": "Madrid", "fecha": "2027-07-16", "hora": "02:30"})
        self.assertContains(r, regreso.codigo)
        r = self.client.get(reverse("vuelos:busqueda"), {"origen": "Madrid", "fecha": "2027-07-15"})
        self.assertEqual(r.context["page_obj"].paginator.count, 0)

    def test_edicion_internacional_y_vinculos(self):
        self.client.post(reverse("vuelos:nuevo_internacional"), {"origen": "Bogotá", "destino": "Madrid",
            "fecha": self.fecha, "hora_salida": "18:00", "horas": 9, "minutos": 0, "costo_persona": "3000000",
            "con_regreso": "on", "fecha_r": self.fecha + timedelta(days=10), "hora_salida_r": "10:00",
            "horas_r": 10, "minutos_r": 0, "costo_persona_r": "3100000"})
        ida = Vuelo.objects.get(tipo="internacional", vuelo_ida__isnull=True)
        regreso = ida.vuelo_regreso
        data = {"origen": "Bogotá", "destino": "Madrid", "fecha": self.fecha, "hora_salida": "19:00",
                "horas": 8, "minutos": 30, "costo_persona": "2900000"}
        ruta = reverse("vuelos:editar", args=[ida.codigo])
        self.assertEqual(self.client.post(ruta, data).status_code, 302)
        ida.refresh_from_db()
        self.assertEqual(ida.duracion_minutos, 510)
        self.assertContains(self.client.post(ruta, dict(data, destino="Miami")), "correspondencia")
        ruta_r = reverse("vuelos:editar", args=[regreso.codigo])
        data_r = dict(data, origen="Madrid", destino="Bogotá", fecha=self.fecha + timedelta(days=11))
        self.assertEqual(self.client.post(ruta_r, data_r).status_code, 302)
        self.assertContains(self.client.post(ruta_r, dict(data_r, fecha=self.fecha - timedelta(days=1))), "después de la llegada")

    def test_paginacion_y_orden(self):
        for n in range(11):
            self.client.post(reverse("vuelos:nuevo_nacional"), self.datos(costo_persona=str(100000+n)))
        r = self.client.get(reverse("vuelos:busqueda"), {"origen": "Pereira", "orden": "costo_persona"})
        self.assertEqual(len(r.context["page_obj"]), 9)
        self.assertEqual(r.context["page_obj"][0].costo_persona, Decimal(100000))
        self.assertContains(r, "origen=Pereira")
        self.assertEqual(len(self.client.get(reverse("vuelos:busqueda"), {"page": 2}).context["page_obj"]), 3)
