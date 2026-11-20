"""Calendario desde la fecha actual, duración automática e imagen elegida por el administrador."""
import io
import os
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from usuarios.models import Usuario
from vuelos import reglas
from vuelos.models import Vuelo

MEDIA_PRUEBAS = tempfile.mkdtemp()


def imagen(nombre="avion.png", formato="PNG"):
    datos = io.BytesIO()
    Image.new("RGB", (40, 20), "skyblue").save(datos, formato)
    return SimpleUploadedFile(nombre, datos.getvalue(), content_type=f"image/{formato.lower()}")


class Base(TestCase):
    def setUp(self):
        self.admin = Usuario.objects.create_user("adm", rol="administrador")
        self.client.force_login(self.admin)
        self.hoy = timezone.localdate()
        self.fecha = self.hoy + timedelta(days=20)

    def nacional(self, **extra):
        return {"origen": "Pereira", "destino": "Bogotá", "fecha": self.fecha, "hora_salida": "08:00",
                "hora_llegada": "09:05", "costo_persona": "250000", **extra}

    def internacional(self, **extra):
        return {"origen": "Bogotá", "destino": "Madrid", "fecha": self.fecha, "hora_salida": "18:00",
                "costo_persona": "3000000", **extra}


class CalendarioDesdeHoy(Base):
    def test_formularios_inician_en_la_fecha_actual(self):
        hoy = self.hoy.isoformat()
        for nombre in ("vuelos:nuevo_nacional", "vuelos:nuevo_internacional"):
            r = self.client.get(reverse(nombre))
            self.assertContains(r, f'name="fecha" value="{hoy}"')
            self.assertContains(r, f'min="{hoy}"')
        # El regreso tampoco permite fechas pasadas.
        self.assertContains(self.client.get(reverse("vuelos:nuevo_internacional")), f'name="fecha_r" min="{hoy}"')

    def test_se_puede_programar_hoy_mas_tarde_pero_no_en_el_pasado(self):
        ahora = timezone.localtime(timezone.now(), reglas.TZ_COLOMBIA)
        if ahora.hour >= 22:
            self.skipTest("Muy tarde para programar un vuelo hoy.")
        salida = (ahora + timedelta(hours=1)).strftime("%H:%M")
        llegada = (ahora + timedelta(hours=2)).strftime("%H:%M")
        r = self.client.post(reverse("vuelos:nuevo_nacional"),
                             self.nacional(fecha=self.hoy, hora_salida=salida, hora_llegada=llegada))
        self.assertEqual(r.status_code, 302)
        r = self.client.post(reverse("vuelos:nuevo_nacional"), self.nacional(fecha=self.hoy - timedelta(days=1)))
        self.assertContains(r, "La salida no puede estar en el pasado.")


class DuracionAutomatica(Base):
    def test_nacional_calcula_duracion_con_las_horas(self):
        self.client.post(reverse("vuelos:nuevo_nacional"), self.nacional())
        self.assertEqual(Vuelo.objects.get().duracion_minutos, 65)

    def test_internacional_sin_duracion_usa_la_estimada_de_la_ruta(self):
        r = self.client.post(reverse("vuelos:nuevo_internacional"), self.internacional())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Vuelo.objects.get().duracion_minutos, reglas.duracion_estimada("Bogotá", "Madrid"))

    def test_internacional_respeta_la_duracion_ajustada(self):
        self.client.post(reverse("vuelos:nuevo_internacional"), self.internacional(horas=9, minutos=45))
        self.assertEqual(Vuelo.objects.get().duracion_minutos, 585)

    def test_regreso_sin_duracion_usa_la_estimada(self):
        self.client.post(reverse("vuelos:nuevo_internacional"), self.internacional(
            con_regreso="on", fecha_r=self.fecha + timedelta(days=7), hora_salida_r="12:00", costo_persona_r="3100000"))
        regreso = Vuelo.objects.get(vuelo_ida__isnull=False)
        self.assertEqual((regreso.origen, regreso.duracion_minutos), ("Madrid", 615))

    def test_estimadas_cubren_todas_las_rutas(self):
        for o in reglas.ORIGENES_INTERNACIONALES:
            for d in reglas.DESTINOS_INTERNACIONALES:
                self.assertIsNotNone(reglas.duracion_estimada(o, d), (o, d))
                self.assertEqual(reglas.duracion_estimada(o, d), reglas.duracion_estimada(d, o))

    def test_calculo_en_vivo(self):
        url = reverse("vuelos:calcular")
        r = self.client.get(url, {"tipo": "nacional", "fecha": "2030-03-01", "hora_salida": "23:30", "hora_llegada": "00:45"})
        self.assertEqual(r.json(), {"minutos": 75, "duracion": "1 h 15 min", "llegada": "02/03/2030 00:45"})
        # Bogotá 18:00 + 10 h 15 min = 04:15 del día siguiente en Bogotá = 10:15 en Madrid (invierno, +6).
        r = self.client.get(url, {"tipo": "internacional", "origen": "Bogotá", "destino": "Madrid",
                                  "fecha": "2030-01-10", "hora_salida": "18:00", "horas": "", "minutos": ""})
        self.assertEqual(r.json(), {"minutos": 615, "duracion": "10 h 15 min", "llegada": "11/01/2030 10:15"})
        for params, error in (({"tipo": "nacional"}, "fecha y la hora"),
                              ({"tipo": "nacional", "fecha": "2030-03-01", "hora_salida": "08:00", "hora_llegada": "08:00"}, "igual"),
                              ({"tipo": "internacional", "fecha": "2030-03-01", "hora_salida": "08:00", "origen": "Cali", "destino": "Pasto"}, "origen y el destino")):
            with self.subTest(params=params):
                r = self.client.get(url, params)
                self.assertEqual(r.status_code, 400)
                self.assertIn(error, r.json()["error"])

    def test_calculo_solo_para_administrador(self):
        url = reverse("vuelos:calcular")
        self.client.force_login(Usuario.objects.create_user("cli", rol="cliente"))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_formulario_incluye_calculo_y_estimaciones(self):
        r = self.client.get(reverse("vuelos:nuevo_internacional"))
        for texto in ('data-calculo-url="/vuelos/calcular/"', 'id="duraciones-estimadas"', '"Bogot\\u00e1|Madrid": 615',
                      "js/vuelo_form.js", 'data-calculo="_r"'):
            self.assertContains(r, texto)


@override_settings(MEDIA_ROOT=MEDIA_PRUEBAS)
class ImagenDelVuelo(Base):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_PRUEBAS, ignore_errors=True)

    def test_vuelo_sin_imagen_usa_ilustracion(self):
        self.client.post(reverse("vuelos:nuevo_nacional"), self.nacional())
        v = Vuelo.objects.get()
        self.assertFalse(v.imagen)
        self.assertIn("img/vuelo-nacional.svg", v.imagen_url)

    def test_imagen_elegida_se_muestra_en_portada_busqueda_y_detalles(self):
        r = self.client.post(reverse("vuelos:nuevo_nacional"), self.nacional(imagen=imagen()))
        self.assertEqual(r.status_code, 302)
        v = Vuelo.objects.get()
        self.assertTrue(v.imagen.name.startswith("vuelos/"))
        for ruta in (reverse("inicio"), reverse("vuelos:busqueda"), reverse("vuelos:publico", args=[v.codigo]),
                     reverse("vuelos:detalle", args=[v.codigo])):
            with self.subTest(ruta):
                self.assertContains(self.client.get(ruta), f'src="{v.imagen.url}"')

    def test_regreso_comparte_la_imagen_de_la_ida(self):
        self.client.post(reverse("vuelos:nuevo_internacional"), self.internacional(
            imagen=imagen("madrid.jpg", "JPEG"), con_regreso="on", fecha_r=self.fecha + timedelta(days=7),
            hora_salida_r="12:00", costo_persona_r="3100000"))
        ida = Vuelo.objects.get(vuelo_ida__isnull=True)
        self.assertTrue(ida.imagen)
        self.assertEqual(ida.vuelo_regreso.imagen.name, ida.imagen.name)

    def test_formato_y_tamano_invalidos(self):
        gif = io.BytesIO()
        Image.new("RGB", (5, 5)).save(gif, "GIF")
        casos = [
            (SimpleUploadedFile("a.gif", gif.getvalue(), content_type="image/gif"), "JPG, PNG o WEBP"),
            (SimpleUploadedFile("falso.png", b"no soy una imagen", content_type="image/png"), "imagen"),
        ]
        for archivo, mensaje in casos:
            with self.subTest(archivo.name):
                r = self.client.post(reverse("vuelos:nuevo_nacional"), self.nacional(imagen=archivo))
                self.assertIn(mensaje, " ".join(r.context["form"].errors["imagen"]))
        datos = io.BytesIO()  # Ruido aleatorio: el PNG no se puede comprimir y pesa más de 3 MB.
        Image.frombytes("RGB", (1100, 1100), os.urandom(1100 * 1100 * 3)).save(datos, "PNG")
        self.assertGreater(len(datos.getvalue()), 3 * 1024 * 1024)
        grande = SimpleUploadedFile("grande.png", datos.getvalue(), content_type="image/png")
        r = self.client.post(reverse("vuelos:nuevo_nacional"), self.nacional(imagen=grande))
        self.assertIn("3 MB", " ".join(r.context["form"].errors["imagen"]))
        self.assertFalse(Vuelo.objects.exists())

    def test_editar_cambia_y_quita_la_imagen(self):
        self.client.post(reverse("vuelos:nuevo_nacional"), self.nacional())
        v = Vuelo.objects.get()
        ruta = reverse("vuelos:editar", args=[v.codigo])
        self.assertEqual(self.client.post(ruta, self.nacional(imagen=imagen("nueva.webp", "WEBP"))).status_code, 302)
        v.refresh_from_db()
        self.assertTrue(v.imagen.name.endswith(".webp"))
        # Guardar sin subir otra imagen la conserva.
        self.client.post(ruta, self.nacional(costo_persona="260000"))
        v.refresh_from_db()
        self.assertTrue(v.imagen)
        # "Limpiar" vuelve a la ilustración.
        self.client.post(ruta, self.nacional(**{"imagen-clear": "on"}))
        v.refresh_from_db()
        self.assertFalse(v.imagen)
