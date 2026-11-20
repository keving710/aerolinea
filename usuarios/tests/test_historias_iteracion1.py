"""Criterios de las HU 1, 2, 10 y 14 según el documento de historias de usuario."""
from django.test import TestCase
from django.urls import reverse

from usuarios.models import Usuario
from usuarios.tests.test_usuarios import CLAVE, DATOS_REGISTRO, crear, crear_ciudad
from vuelos.models import Consecutivo


class HU1MensajesRegistro(TestCase):
    def setUp(self):
        self.datos = {**DATOS_REGISTRO, "ciudad_nacimiento": crear_ciudad("Pereira", "Risaralda").pk}

    def test_cuenta_existente_muestra_mensaje(self):
        self.client.post(reverse("usuarios:registro"), self.datos)
        self.client.post(reverse("usuarios:logout"))
        r = self.client.post(reverse("usuarios:registro"), {**self.datos, "username": "otra"})
        self.assertContains(r, "Ya existe una cuenta registrada con este documento de identidad.")
        self.assertContains(r, "Ya existe una cuenta registrada con este correo electrónico.")

    def test_correo_duplicado_sin_importar_mayusculas(self):
        self.client.post(reverse("usuarios:registro"), self.datos)
        self.client.post(reverse("usuarios:logout"))
        r = self.client.post(reverse("usuarios:registro"), {
            **self.datos, "username": "otra", "dni": "999", "email": "ANA@Correo.com"})
        self.assertContains(r, "Ya existe una cuenta registrada con este correo electrónico.")
        self.assertEqual(Usuario.objects.filter(rol="cliente").count(), 1)

    def test_correo_se_guarda_en_minusculas(self):
        self.client.post(reverse("usuarios:registro"), {**self.datos, "email": "Ana@Correo.COM"})
        self.assertEqual(Usuario.objects.get(username="ana").email, "ana@correo.com")

    def test_indica_cual_campo_falta(self):
        r = self.client.post(reverse("usuarios:registro"), {**self.datos, "direccion_facturacion": "", "dni": ""})
        self.assertContains(r, "Corrige los siguientes campos:")
        self.assertContains(r, "Dirección de facturación</a>: Este campo es obligatorio.")
        self.assertContains(r, "Documento de identidad</a>: Este campo es obligatorio.")


class HU2MensajeInicioSesion(TestCase):
    def test_login_exitoso_muestra_mensaje(self):
        crear("cli", "cliente", first_name="Ana", last_name="Pérez")
        r = self.client.post(reverse("usuarios:login"), {"username": "cli", "password": CLAVE}, follow=True)
        self.assertContains(r, "Iniciaste sesión correctamente.")

    def test_login_fallido_indica_credencial_incorrecta(self):
        crear("cli", "cliente")
        r = self.client.post(reverse("usuarios:login"), {"username": "cli", "password": "mala"})
        self.assertContains(r, "Usuario o contraseña incorrectos.")


class HU10CodigoSoloLectura(TestCase):
    def setUp(self):
        crear("adm", "administrador")
        self.client.login(username="adm", password=CLAVE)

    def test_formularios_muestran_codigo_siguiente_de_solo_lectura(self):
        Consecutivo.objects.create(nombre="vuelo", ultimo=41)
        for nombre in ("vuelos:nuevo_nacional", "vuelos:nuevo_internacional"):
            r = self.client.get(reverse(nombre))
            self.assertContains(r, 'value="VU-00042" readonly')
            self.assertNotIn("codigo", r.context["form"].fields)

    def test_primer_vuelo(self):
        self.assertContains(self.client.get(reverse("vuelos:nuevo_nacional")), 'value="VU-00001" readonly')


class HU14ResumenDeErrores(TestCase):
    def test_vuelo_invalido_lista_cada_error(self):
        crear("adm", "administrador")
        self.client.login(username="adm", password=CLAVE)
        r = self.client.post(reverse("vuelos:nuevo_nacional"), {"origen": "Cali", "destino": "Cali"})
        self.assertContains(r, "Corrige los siguientes campos:")
        for etiqueta in ("Destino", "Fecha de salida", "Hora de salida", "Hora de llegada", "Costo por persona (COP)"):
            self.assertContains(r, f"{etiqueta}</a>:")
