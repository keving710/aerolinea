import re
from datetime import date

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.formats import number_format

from finanzas.models import Tarjeta
from usuarios.models import Usuario
from vuelos.catalogo import disponibles

from . import servicios
from .models import Tiquete

TELEFONO = re.compile(r"^\+?[0-9][0-9 ]{6,18}[0-9]$")
DOCUMENTO = re.compile(r"^[A-Za-z0-9]{5,20}$")


class ViajeroForm(forms.Form):
    """Datos de un viajero: todos son obligatorios (HU 27) y la clase se elige aquí (HU 30)."""

    documento = forms.CharField(label="Documento", max_length=20)
    nombres = forms.CharField(label="Nombres", max_length=100)
    apellidos = forms.CharField(label="Apellidos", max_length=100)
    fecha_nacimiento = forms.DateField(label="Fecha de nacimiento", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    genero = forms.ChoiceField(label="Género", choices=[("", "Selecciona")] + list(Usuario.Genero.choices))
    telefono = forms.CharField(label="Teléfono", max_length=20)
    correo = forms.EmailField(label="Correo electrónico", max_length=254)
    contacto_nombre = forms.CharField(label="Nombre de un contacto", max_length=120)
    contacto_telefono = forms.CharField(label="Teléfono del contacto", max_length=20)
    clase = forms.ChoiceField(label="Clase", choices=Tiquete.Clase.choices, initial=Tiquete.Clase.ECONOMICA)

    def clean_documento(self):
        valor = self.cleaned_data["documento"].strip().upper()
        if not DOCUMENTO.match(valor):
            raise ValidationError("El documento debe tener entre 5 y 20 letras o números, sin espacios ni símbolos.")
        return valor

    def _texto(self, campo):
        valor = " ".join(self.cleaned_data[campo].split())
        if not valor:
            raise ValidationError("Este campo es obligatorio.")
        return valor

    clean_nombres = lambda self: self._texto("nombres")  # noqa: E731
    clean_apellidos = lambda self: self._texto("apellidos")  # noqa: E731
    clean_contacto_nombre = lambda self: self._texto("contacto_nombre")  # noqa: E731

    def clean_fecha_nacimiento(self):
        valor = self.cleaned_data["fecha_nacimiento"]
        hoy = date.today()
        if valor > hoy:
            raise ValidationError("La fecha de nacimiento no puede ser futura.")
        if servicios.edad_en(valor, hoy) > 120:
            raise ValidationError("La fecha de nacimiento no es válida.")
        return valor

    def _telefono(self, campo):
        valor = self.cleaned_data[campo].strip()
        if not TELEFONO.match(valor):
            raise ValidationError("Ingresa un teléfono válido, solo con números (puede iniciar con +).")
        return valor

    clean_telefono = lambda self: self._telefono("telefono")  # noqa: E731
    clean_contacto_telefono = lambda self: self._telefono("contacto_telefono")  # noqa: E731

    def clean_correo(self):
        return self.cleaned_data["correo"].strip().lower()


class BaseViajeroFormSet(forms.BaseFormSet):
    """Reglas entre viajeros: sin repetidos y no solo menores de edad."""

    fecha_viaje = None

    def clean(self):
        super().clean()
        if any(f.errors for f in self.forms):
            return
        datos = [f.cleaned_data for f in self.forms if f.cleaned_data]
        documentos = [d["documento"] for d in datos]
        if len(set(documentos)) != len(documentos):
            raise ValidationError("Un mismo viajero no puede repetirse: revisa los documentos.")
        servicios.validar_menores(datos, self.fecha_viaje or date.today())


ViajerosFormSet = forms.formset_factory(
    ViajeroForm, formset=BaseViajeroFormSet, extra=0, min_num=1, max_num=servicios.LIMITE_POR_VUELO,
    validate_min=True, validate_max=True)


class TrayectoForm(forms.Form):
    """Solo ida u ida y vuelta (HU 29)."""

    trayecto = forms.ChoiceField(label="Trayecto", choices=[("unico", "Solo ida"), ("completo", "Ida y vuelta")],
                                 initial="unico", widget=forms.RadioSelect(attrs={"class": "form-check-input"}))
    regreso = forms.ChoiceField(label="Vuelo de regreso", required=False)

    def __init__(self, vuelo, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.vuelo = vuelo
        self.opciones = list(disponibles().filter(origen=vuelo.destino, destino=vuelo.origen, tipo=vuelo.tipo,
                                                  salida__gt=vuelo.llegada).order_by("salida"))
        self.fields["regreso"].choices = [("", "Selecciona el vuelo de regreso")] + [
            (v.codigo, f"{v.codigo} · {v.salida_local} · ${number_format(v.costo_vigente, 0, force_grouping=True)}")
            for v in self.opciones]

    def clean(self):
        datos = super().clean()
        if datos.get("trayecto") == "completo" and not datos.get("regreso"):
            self.add_error("regreso", "Selecciona el vuelo de regreso para un viaje de ida y vuelta.")
        if datos.get("trayecto") != "completo":
            datos["regreso"] = ""
        return datos


class PagoForm(forms.Form):
    """Elección de la tarjeta con la que se paga (HU 29 y 38)."""

    tarjeta = forms.ModelChoiceField(label="Tarjeta de pago", queryset=Tarjeta.objects.none(), empty_label="Selecciona una tarjeta")
    total = forms.DecimalField(widget=forms.HiddenInput, max_digits=14, decimal_places=2)

    def __init__(self, usuario, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hoy = timezone.localdate()
        cartas = (Tarjeta.objects.filter(cliente=usuario).exclude(anio_vencimiento__lt=hoy.year)
                  .exclude(anio_vencimiento=hoy.year, mes_vencimiento__lt=hoy.month))
        self.fields["tarjeta"].queryset = cartas
        self.fields["tarjeta"].label_from_instance = lambda t: f"{t} · Saldo COP {number_format(t.saldo, 2, force_grouping=True)}"
