"""Tarjetas simuladas: franquicia, dígito verificador, CVV y vencimiento."""
import uuid
from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.models import Usuario
from . import services
from .models import Tarjeta

# Números de prueba públicos (pasan el algoritmo de Luhn).
NUMEROS = {
    "visa": "4111111111111111",
    "mastercard": "5555555555554444",
    "amex": "378282246310005",
    "diners": "30569309025904",
    "discover": "6011111111111117",
    "jcb": "3530111333300000",
}


class FranquiciasYValidaciones(TestCase):
    def test_detecta_cada_franquicia(self):
        for esperada, numero in NUMEROS.items():
            with self.subTest(esperada):
                self.assertEqual(services.validar_numero(numero), (numero, esperada))
        self.assertEqual(services.detectar_franquicia("2221000000000009"), "mastercard")

    def test_rechaza_franquicia_desconocida_luhn_y_longitud(self):
        casos = {
            "9111111111111111": "No reconocemos la franquicia",
            "4111111111111112": "no es válido",
            "37828224631000": "debe tener 15 dígitos",
        }
        for numero, mensaje in casos.items():
            with self.subTest(numero), self.assertRaisesMessage(ValidationError, mensaje):
                services.validar_numero(numero)

    def test_cvv_segun_franquicia(self):
        services.validar_cvv("123", "visa")
        services.validar_cvv("1234", "amex")
        for cvv, franquicia in (("12", "visa"), ("1234", "visa"), ("123", "amex"), ("12a", "mastercard"), ("", "visa")):
            with self.subTest(cvv=cvv, franquicia=franquicia), self.assertRaises(ValidationError):
                services.validar_cvv(cvv, franquicia)

    def test_vencimiento(self):
        hoy = date(2026, 11, 20)
        self.assertEqual(services.validar_vencimiento("11", "26", hoy), (11, 2026))  # vigente hasta fin de mes
        self.assertEqual(services.validar_vencimiento("1", "2030", hoy), (1, 2030))
        for mes, anio, mensaje in (("10", "26", "vencida"), ("13", "30", "entre 01 y 12"),
                                   ("00", "30", "entre 01 y 12"), ("01", "60", "no es válida")):
            with self.subTest(mes=mes, anio=anio), self.assertRaisesMessage(ValidationError, mensaje):
                services.validar_vencimiento(mes, anio, hoy)


class RegistroYUsoDeTarjetas(TestCase):
    def setUp(self):
        self.ana = Usuario.objects.create_user("ana", rol="cliente")
        self.client.force_login(self.ana)
        self.ruta = reverse("finanzas:nueva_tarjeta")

    def datos(self, **extra):
        return {"numero": "3782 822463 10005", "vencimiento": "08/39", "cvv": "1234",
                "tipo": "credito", "saldo": "500000", **extra}

    def test_registro_guarda_franquicia_vencimiento_y_numero_visible_sin_cvv(self):
        self.assertRedirects(self.client.post(self.ruta, self.datos()), reverse("finanzas:panel"))
        t = Tarjeta.objects.get()
        self.assertEqual((t.franquicia, t.mes_vencimiento, t.anio_vencimiento, t.ultimos_cuatro), ("amex", 8, 2039, "0005"))
        self.assertEqual(str(t), "American Express Crédito 3782 822463 10005")
        guardado = str(t.__dict__)
        self.assertNotIn("1234", guardado)
        self.assertEqual(t.numero_completo, "378282246310005")
        panel = self.client.get(reverse("finanzas:panel"))
        self.assertContains(panel, "American Express")
        self.assertContains(panel, "3782 822463 10005")
        self.assertContains(panel, "Vence 08/39")

    def test_errores_por_campo(self):
        casos = [
            ({"cvv": "123"}, "cvv", "tiene 4 dígitos"),
            ({"vencimiento": "01/20"}, "vencimiento", "vencida"),
            ({"vencimiento": "0839"}, "vencimiento", "MM/AA"),
            ({"numero": "9111111111111111"}, "numero", "No reconocemos la franquicia"),
            ({"numero": "4111111111111112"}, "numero", "no es válido"),
        ]
        for extra, campo, mensaje in casos:
            with self.subTest(campo=campo, extra=extra):
                r = self.client.post(self.ruta, self.datos(**extra))
                self.assertIn(mensaje, " ".join(r.context["form"].errors[campo]))
        self.assertFalse(Tarjeta.objects.exists())

    def test_formulario_muestra_campos_y_detector(self):
        r = self.client.get(self.ruta)
        for texto in ('name="vencimiento"', 'name="cvv"', "data-franquicia", "js/tarjeta.js"):
            self.assertContains(r, texto)

    def test_tarjeta_vencida_no_paga_ni_recarga_pero_si_recibe_reembolso(self):
        t = services.registrar_tarjeta(self.ana, NUMEROS["visa"], "debito", "1000", mes=12, anio=2040, cvv="123")
        hoy = timezone.localdate()
        Tarjeta.objects.filter(pk=t.pk).update(mes_vencimiento=1, anio_vencimiento=hoy.year - 1)
        for servicio in (services.cobrar, services.recargar):
            with self.subTest(servicio.__name__), self.assertRaisesMessage(ValidationError, "venció"):
                servicio(self.ana, t.pk, "10", uuid.uuid4())
        services.reembolsar(self.ana, t.pk, "10", uuid.uuid4())
        r = self.client.get(reverse("finanzas:simular_pago"))
        self.assertNotIn(t, r.context["form"].fields["tarjeta"].queryset)
        self.assertContains(self.client.get(reverse("finanzas:panel")), "Vencida")
