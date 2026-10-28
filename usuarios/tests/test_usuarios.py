from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from usuarios.models import Ciudad, Departamento, Usuario
from usuarios.validadores import ComplejidadPasswordValidator

CLAVE = "Clave-Segura-2026"


def crear(username, rol, **extra):
    return Usuario.objects.create_user(username=username, password=CLAVE, rol=rol, **extra)


def crear_ciudad(nombre, departamento):
    dep, _ = Departamento.objects.get_or_create(nombre=departamento)
    ciudad, _ = Ciudad.objects.get_or_create(nombre=nombre, departamento=dep)
    return ciudad


DATOS_REGISTRO = {
    "first_name": "Ana", "last_name": "Pérez", "dni": "1088000111", "email": "ana@correo.com",
    "fecha_nacimiento": "2000-05-14", "direccion_facturacion": "Cra 8 # 24-15",
    "genero": "femenino", "username": "ana", "password1": CLAVE, "password2": CLAVE,
}


class HU1Registro(TestCase):
    def setUp(self):
        self.pereira = crear_ciudad("Pereira", "Risaralda")
        self.datos = {**DATOS_REGISTRO, "ciudad_nacimiento": self.pereira.pk}

    def test_registro_exitoso_crea_cliente_y_abre_sesion(self):
        r = self.client.post(reverse("usuarios:registro"), self.datos)
        self.assertRedirects(r, reverse("inicio"))
        u = Usuario.objects.get(username="ana")
        self.assertEqual(u.rol, "cliente")
        self.assertEqual(u.ciudad_nacimiento, self.pereira)
        self.assertTrue(u.perfil_completo)
        self.assertIn("_auth_user_id", self.client.session)

    def test_documento_o_correo_duplicado_se_rechaza(self):
        self.client.post(reverse("usuarios:registro"), self.datos)
        self.client.post(reverse("usuarios:salir") if False else reverse("usuarios:logout"))
        otro = {**self.datos, "username": "ana2"}
        r = self.client.post(reverse("usuarios:registro"), otro)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Usuario.objects.filter(rol="cliente").count(), 1)

    def test_campos_obligatorios(self):
        datos = {**self.datos, "direccion_facturacion": ""}
        r = self.client.post(reverse("usuarios:registro"), datos)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username="ana").exists())

    def test_ciudad_obligatoria(self):
        datos = {**self.datos, "ciudad_nacimiento": ""}
        r = self.client.post(reverse("usuarios:registro"), datos)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username="ana").exists())

    def test_fecha_nacimiento_futura_se_rechaza(self):
        datos = {**self.datos, "fecha_nacimiento": "2999-01-01"}
        r = self.client.post(reverse("usuarios:registro"), datos)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username="ana").exists())

    def test_menor_de_edad_se_rechaza(self):
        datos = {**self.datos, "fecha_nacimiento": "2020-01-01"}
        r = self.client.post(reverse("usuarios:registro"), datos)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username="ana").exists())

    def test_contrasenas_distintas(self):
        r = self.client.post(reverse("usuarios:registro"), {**self.datos, "password2": "otra"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username="ana").exists())


class HU2Sesion(TestCase):
    def setUp(self):
        crear("cli", "cliente")

    def test_login_correcto_e_incorrecto(self):
        r = self.client.post(reverse("usuarios:login"), {"username": "cli", "password": "mala"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        r = self.client.post(reverse("usuarios:login"), {"username": "cli", "password": CLAVE})
        self.assertRedirects(r, reverse("inicio"))

    def test_logout(self):
        self.client.login(username="cli", password=CLAVE)
        self.client.post(reverse("usuarios:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_solo_por_post(self):
        self.client.login(username="cli", password=CLAVE)
        self.assertEqual(self.client.get(reverse("usuarios:logout")).status_code, 405)

    def test_redireccion_por_rol(self):
        crear("adm", "administrador")
        r = self.client.post(reverse("usuarios:login"), {"username": "adm", "password": CLAVE})
        self.assertRedirects(r, reverse("vuelos:lista"))
        self.client.post(reverse("usuarios:logout"))
        r = self.client.post(reverse("usuarios:login"), {"username": "root", "password": "Root2026!"})
        self.assertRedirects(r, reverse("usuarios:administradores"))


class HU3Acceso(TestCase):
    def setUp(self):
        crear("cli", "cliente")
        crear("adm", "administrador")

    def entrar(self, usuario, clave=CLAVE):
        self.client.login(username=usuario, password=clave)

    def test_visitante_es_enviado_a_login(self):
        for nombre in ["usuarios:perfil", "usuarios:administradores", "vuelos:lista"]:
            r = self.client.get(reverse(nombre))
            self.assertEqual(r.status_code, 302, nombre)
            self.assertIn(reverse("usuarios:login"), r["Location"])

    def test_cliente_no_accede_a_admin_ni_root(self):
        self.entrar("cli")
        for nombre in ["usuarios:administradores", "usuarios:root_credenciales", "vuelos:lista", "vuelos:nuevo_nacional"]:
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 403, nombre)

    def test_admin_no_accede_a_secciones_root(self):
        self.entrar("adm")
        for nombre in ["usuarios:administradores", "usuarios:administrador_nuevo", "usuarios:root_credenciales"]:
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 403, nombre)
        self.assertEqual(self.client.get(reverse("vuelos:lista")).status_code, 200)

    def test_root_no_gestiona_vuelos_ni_perfil(self):
        self.entrar("root", "Root2026!")
        self.assertEqual(self.client.get(reverse("vuelos:lista")).status_code, 403)
        self.assertEqual(self.client.get(reverse("vuelos:nuevo_nacional")).status_code, 403)
        self.assertEqual(self.client.get(reverse("usuarios:perfil")).status_code, 403)
        self.assertEqual(self.client.get(reverse("usuarios:administradores")).status_code, 200)


class HU4Root(TestCase):
    def test_root_existe_tras_migrar(self):
        root = Usuario.objects.get(rol="root")
        self.assertEqual(root.username, "root")
        self.assertTrue(root.check_password("Root2026!"))

    def entrar(self):
        self.client.login(username="root", password="Root2026!")

    def test_cambiar_usuario_y_contrasena(self):
        self.entrar()
        r = self.client.post(reverse("usuarios:root_credenciales"), {
            "username": "superroot", "password_actual": "Root2026!",
            "password1": "Nueva-Clave-9876", "password2": "Nueva-Clave-9876"})
        self.assertRedirects(r, reverse("usuarios:root_credenciales"))
        root = Usuario.objects.get(rol="root")
        self.assertEqual(root.username, "superroot")
        self.assertTrue(root.check_password("Nueva-Clave-9876"))
        # La sesión sigue activa tras cambiar la clave.
        self.assertEqual(self.client.get(reverse("usuarios:administradores")).status_code, 200)

    def test_exige_contrasena_actual(self):
        self.entrar()
        self.client.post(reverse("usuarios:root_credenciales"), {"username": "otro", "password_actual": "mala"})
        self.assertEqual(Usuario.objects.get(rol="root").username, "root")

    def test_el_root_solo_edita_id_y_contrasena(self):
        from usuarios.forms import RootCredencialesForm
        self.assertEqual(list(RootCredencialesForm.Meta.fields), ["username"])


class HU5Administradores(TestCase):
    def test_root_crea_administrador_que_puede_ingresar(self):
        self.client.login(username="root", password="Root2026!")
        r = self.client.post(reverse("usuarios:administrador_nuevo"),
                             {"username": "admin1", "password1": CLAVE, "password2": CLAVE})
        self.assertRedirects(r, reverse("usuarios:administradores"))
        self.assertEqual(Usuario.objects.get(username="admin1").rol, "administrador")
        self.client.logout()
        self.assertTrue(self.client.login(username="admin1", password=CLAVE))

    def test_usuario_repetido(self):
        crear("admin1", "administrador")
        self.client.login(username="root", password="Root2026!")
        r = self.client.post(reverse("usuarios:administrador_nuevo"),
                             {"username": "admin1", "password1": CLAVE, "password2": CLAVE})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Usuario.objects.filter(username="admin1").count(), 1)


class HU6HU7Perfil(TestCase):
    def setUp(self):
        self.cali = crear_ciudad("Cali", "Valle del Cauca")
        self.armenia = crear_ciudad("Armenia", "Quindío")

    def datos(self, **extra):
        return {"first_name": "Luis", "last_name": "Gómez", "dni": "123456", "email": "luis@x.com",
                "fecha_nacimiento": "1999-01-20", "ciudad_nacimiento": self.cali.pk,
                "direccion_facturacion": "Calle 1 # 2-3", "genero": "masculino", **extra}

    def test_admin_nuevo_ve_aviso_y_completa_perfil(self):
        crear("adm", "administrador")
        self.client.login(username="adm", password=CLAVE)
        self.assertContains(self.client.get(reverse("usuarios:perfil")), "incompleto")
        r = self.client.post(reverse("usuarios:perfil"), self.datos())
        self.assertRedirects(r, reverse("usuarios:perfil"))
        self.assertTrue(Usuario.objects.get(username="adm").perfil_completo)
        self.assertNotContains(self.client.get(reverse("usuarios:perfil")), "incompleto")

    def test_perfil_incompleto_no_se_guarda(self):
        crear("adm", "administrador")
        self.client.login(username="adm", password=CLAVE)
        r = self.client.post(reverse("usuarios:perfil"), self.datos(first_name=""))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Usuario.objects.get(username="adm").perfil_completo)

    def test_cliente_edita_su_perfil(self):
        crear("cli", "cliente")
        self.client.login(username="cli", password=CLAVE)
        self.client.post(reverse("usuarios:perfil"), self.datos(ciudad_nacimiento=self.armenia.pk))
        self.assertEqual(Usuario.objects.get(username="cli").ciudad_nacimiento, self.armenia)

    def test_dni_duplicado_entre_usuarios(self):
        crear("otro", "cliente", dni="123456")
        crear("cli", "cliente")
        self.client.login(username="cli", password=CLAVE)
        r = self.client.post(reverse("usuarios:perfil"), self.datos())
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(Usuario.objects.get(username="cli").dni)

    def test_foto_formato_y_tamano(self):
        import tempfile
        crear("cli", "cliente")
        self.client.login(username="cli", password=CLAVE)
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            gif = SimpleUploadedFile("a.gif", b"GIF89a", content_type="image/gif")
            self.assertEqual(self.client.post(reverse("usuarios:perfil"), self.datos(foto=gif)).status_code, 200)
            grande = SimpleUploadedFile("a.png", b"0" * (2 * 1024 * 1024 + 1), content_type="image/png")
            self.assertEqual(self.client.post(reverse("usuarios:perfil"), self.datos(foto=grande)).status_code, 200)
            self.assertFalse(Usuario.objects.get(username="cli").foto)

    def test_foto_valida(self):
        import io, tempfile
        from PIL import Image
        crear("cli", "cliente")
        self.client.login(username="cli", password=CLAVE)
        buf = io.BytesIO()
        Image.new("RGB", (10, 10), "red").save(buf, "PNG")
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            png = SimpleUploadedFile("yo.png", buf.getvalue(), content_type="image/png")
            r = self.client.post(reverse("usuarios:perfil"), self.datos(foto=png))
            self.assertRedirects(r, reverse("usuarios:perfil"))
            self.assertTrue(Usuario.objects.get(username="cli").foto)


class Contrasenas(TestCase):
    """Criterios de contraseña: mayúscula, minúscula, número, carácter especial y sin espacios."""

    def setUp(self):
        self.validador = ComplejidadPasswordValidator()
        self.pereira = crear_ciudad("Pereira", "Risaralda")

    def registro(self, clave):
        datos = {**DATOS_REGISTRO, "ciudad_nacimiento": self.pereira.pk,
                 "password1": clave, "password2": clave}
        return self.client.post(reverse("usuarios:registro"), datos)

    def test_clave_valida(self):
        self.validador.validate("Clave-Segura-2026")  # no debe lanzar error

    def test_rechaza_cada_criterio_incumplido(self):
        casos = {
            "sin mayúscula": "clave-segura-2026",
            "sin minúscula": "CLAVE-SEGURA-2026",
            "sin número": "Clave-Segura-abcd",
            "sin carácter especial": "ClaveSegura2026",
            "con espacios": "Clave Segura-2026",
        }
        for criterio, clave in casos.items():
            with self.subTest(criterio=criterio):
                with self.assertRaises(ValidationError):
                    self.validador.validate(clave)

    def test_registro_rechaza_clave_sin_mayuscula(self):
        r = self.registro("clave-segura-2026")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username="ana").exists())

    def test_registro_rechaza_clave_con_espacios(self):
        r = self.registro("Clave Segura 2026!")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username="ana").exists())

    def test_registro_rechaza_clave_corta(self):
        r = self.registro("Ab-1")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username="ana").exists())