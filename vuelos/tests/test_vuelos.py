from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.models import Usuario
from vuelos.models import Consecutivo, Vuelo

CLAVE = "Clave-Segura-2026"


def fecha_futura(dias=30):
    return (timezone.localtime() + timedelta(days=dias)).date()


class Base(TestCase):
    def setUp(self):
        self.admin = Usuario.objects.create_user("adm", password=CLAVE, rol="administrador")
        self.client.login(username="adm", password=CLAVE)

    def nacional(self, **extra):
        datos = {"origen": "Pereira", "destino": "Bogotá", "fecha": fecha_futura(),
                 "hora_salida": "08:00", "hora_llegada": "09:05", "costo_persona": "250000"}
        datos.update(extra)
        return self.client.post(reverse("vuelos:nuevo_nacional"), datos)

    def internacional(self, **extra):
        datos = {"origen": "Bogotá", "destino": "Madrid", "fecha": fecha_futura(),
                 "hora_salida": "18:00", "horas": 9, "minutos": 30, "costo_persona": "3500000"}
        datos.update(extra)
        return self.client.post(reverse("vuelos:nuevo_internacional"), datos)


class HU10Consecutivo(Base):
    def test_codigos_consecutivos_y_unicos(self):
        self.nacional()
        self.nacional(destino="Cali")
        codigos = list(Vuelo.objects.order_by("id").values_list("codigo", flat=True))
        self.assertEqual(codigos, ["VU-00001", "VU-00002"])
        self.assertEqual(Consecutivo.objects.get(nombre="vuelo").ultimo, 2)

    def test_vuelo_invalido_no_consume_codigo(self):
        self.nacional(destino="Pereira")
        self.assertEqual(Vuelo.objects.count(), 0)
        self.nacional()
        self.assertEqual(Vuelo.objects.get().codigo, "VU-00001")


class HU11Nacional(Base):
    def test_crea_vuelo_y_calcula_duracion(self):
        r = self.nacional()
        v = Vuelo.objects.get()
        self.assertRedirects(r, reverse("vuelos:detalle", args=[v.codigo]))
        self.assertEqual(v.duracion_minutos, 65)
        self.assertEqual(v.capacidad, 150)
        self.assertEqual(v.tipo, "nacional")
        self.assertEqual(v.estado, "programado")
        self.assertEqual(v.creado_por, self.admin)

    def test_llegada_dia_siguiente(self):
        self.nacional(hora_salida="23:30", hora_llegada="00:45")
        v = Vuelo.objects.get()
        self.assertEqual(v.duracion_minutos, 75)

    def test_origen_igual_destino(self):
        self.assertEqual(self.nacional(destino="Pereira").status_code, 200)
        self.assertEqual(Vuelo.objects.count(), 0)

    def test_fecha_pasada(self):
        self.nacional(fecha=fecha_futura(-2))
        self.assertEqual(Vuelo.objects.count(), 0)

    def test_hora_pasada_hoy(self):
        ahora = timezone.localtime()
        antes = ahora - timedelta(hours=1)
        if antes.date() == ahora.date():
            self.nacional(fecha=ahora.date(), hora_salida=antes.strftime("%H:%M"), hora_llegada="23:59")
            self.assertEqual(Vuelo.objects.count(), 0)

    def test_horas_iguales_y_campos_vacios(self):
        self.nacional(hora_llegada="08:00")
        self.nacional(costo_persona="")
        self.nacional(origen="Gotham")
        self.assertEqual(Vuelo.objects.count(), 0)

    def test_costo_debe_ser_positivo(self):
        self.nacional(costo_persona="0")
        self.assertEqual(Vuelo.objects.count(), 0)


class HU12HU13Internacional(Base):
    def test_crea_vuelo_internacional(self):
        self.internacional()
        v = Vuelo.objects.get()
        self.assertEqual(v.capacidad, 250)
        self.assertEqual(v.duracion_minutos, 570)
        self.assertEqual(v.llegada - v.salida, timedelta(minutes=570))

    def test_llegada_en_hora_local_del_destino(self):
        # Bogotá 2027-01-15 10:00 + 9 h -> Madrid 16/01 01:00 (invierno)
        self.internacional(fecha="2027-01-15", hora_salida="10:00", horas=9, minutos=0)
        self.assertEqual(Vuelo.objects.get().llegada_local, "16/01/2027 01:00")

    def test_horario_de_verano_de_madrid(self):
        self.internacional(fecha="2027-07-15", hora_salida="10:00", horas=9, minutos=0)
        self.assertEqual(Vuelo.objects.get().llegada_local, "16/07/2027 02:00")

    def test_rutas_no_permitidas(self):
        self.internacional(origen="Arauca")
        self.internacional(destino="Tokio")
        self.assertEqual(Vuelo.objects.count(), 0)

    def test_duracion_cero(self):
        self.internacional(horas=0, minutos=0)
        self.assertEqual(Vuelo.objects.count(), 0)

    def test_ida_y_regreso_vinculados(self):
        self.internacional(con_regreso="on", fecha_r=fecha_futura(40), hora_salida_r="12:00",
                           horas_r=10, minutos_r=0, costo_persona_r="3400000")
        ida, regreso = Vuelo.objects.order_by("id")
        self.assertEqual((regreso.origen, regreso.destino), ("Madrid", "Bogotá"))
        self.assertEqual(regreso.vuelo_ida, ida)
        self.assertEqual(ida.vuelo_regreso, regreso)

    def test_regreso_antes_de_la_llegada_se_rechaza(self):
        self.internacional(con_regreso="on", fecha_r=fecha_futura(30), hora_salida_r="00:00",
                           horas_r=10, minutos_r=0, costo_persona_r="3400000")
        self.assertEqual(Vuelo.objects.count(), 0)

    def test_regreso_incompleto_se_rechaza(self):
        self.internacional(con_regreso="on")
        self.assertEqual(Vuelo.objects.count(), 0)

    def test_agregar_regreso_despues(self):
        self.internacional()
        ida = Vuelo.objects.get()
        r = self.client.post(reverse("vuelos:regreso", args=[ida.codigo]), {
            "fecha": fecha_futura(45), "hora_salida": "09:00", "horas": 10, "minutos": 0, "costo_persona": "3300000"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Vuelo.objects.count(), 2)
        # Segundo intento: ya tiene regreso.
        self.client.post(reverse("vuelos:regreso", args=[ida.codigo]), {
            "fecha": fecha_futura(50), "hora_salida": "09:00", "horas": 10, "minutos": 0, "costo_persona": "1"})
        self.assertEqual(Vuelo.objects.count(), 2)

    def test_regreso_no_aplica_a_nacionales(self):
        self.nacional()
        v = Vuelo.objects.get()
        self.assertEqual(self.client.get(reverse("vuelos:regreso", args=[v.codigo])).status_code, 404)


class HU14Validacion(Base):
    def test_vuelo_publicado_solo_si_es_valido_y_aparece_en_lista(self):
        self.nacional(destino="Pereira")
        self.assertEqual(Vuelo.objects.count(), 0)
        self.nacional()
        r = self.client.get(reverse("vuelos:lista"))
        self.assertContains(r, "VU-00001")
        self.assertContains(r, "08:00")

    def test_errores_visibles_para_el_administrador(self):
        r = self.nacional(destino="Pereira")
        self.assertContains(r, "misma ciudad")

    def test_codigo_no_editable(self):
        self.nacional()
        v = Vuelo.objects.get()
        self.assertFalse(Vuelo._meta.get_field("codigo").editable)
        self.assertEqual(v.codigo, "VU-00001")

    def test_detalle(self):
        self.nacional()
        self.assertContains(self.client.get(reverse("vuelos:detalle", args=["VU-00001"])), "Pereira")
