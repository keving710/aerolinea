import uuid
from decimal import Decimal

from django import forms
from django.utils import timezone
from django.utils.formats import number_format

import re

from .models import Tarjeta
from .services import FRANQUICIAS_TEXTO, validar_cvv, validar_numero, validar_vencimiento


class TarjetaForm(forms.Form):
    numero = forms.CharField(
        label="Número de tarjeta ficticia", max_length=25,
        widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
        help_text=f"Solo simulación, no ingreses datos reales. Aceptamos {FRANQUICIAS_TEXTO}; "
                  "la franquicia se detecta con los primeros dígitos.")
    vencimiento = forms.CharField(
        label="Fecha de vencimiento", max_length=7,
        widget=forms.TextInput(attrs={"placeholder": "MM/AA", "inputmode": "numeric", "autocomplete": "off"}),
        help_text="Mes y año, por ejemplo 08/29.")
    cvv = forms.CharField(
        label="Código de seguridad (CVV)", max_length=4,
        widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
        help_text="3 dígitos (4 en American Express). Solo se valida, nunca se guarda.")
    tipo = forms.ChoiceField(label="Tipo de tarjeta", choices=Tarjeta.Tipo.choices)
    saldo = forms.DecimalField(label="Saldo inicial simulado (COP)", min_value=0,
                               max_digits=14, decimal_places=2, initial=0)

    def clean_numero(self):
        numero, self.franquicia = validar_numero(self.cleaned_data["numero"])
        return numero

    def clean_vencimiento(self):
        texto = self.cleaned_data["vencimiento"].replace(" ", "")
        partes = re.fullmatch(r"(\d{1,2})/(\d{2}|\d{4})", texto)
        if not partes:
            raise forms.ValidationError("Escribe la fecha de vencimiento como MM/AA.")
        return validar_vencimiento(*partes.groups())

    def clean(self):
        datos = super().clean()
        if datos.get("numero") and datos.get("cvv") is not None:
            try:
                validar_cvv(datos["cvv"], self.franquicia)
            except forms.ValidationError as exc:
                self.add_error("cvv", exc)
        return datos


class OperacionForm(forms.Form):
    tarjeta = forms.ModelChoiceField(label="Tarjeta", queryset=Tarjeta.objects.none())
    valor = forms.DecimalField(label="Valor (COP)", min_value=Decimal("0.01"), max_digits=14, decimal_places=2)
    referencia = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, usuario, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tarjeta"].queryset = Tarjeta.objects.filter(cliente=usuario)
        # Las tarjetas vencidas no se ofrecen para pagar ni recargar.
        hoy = timezone.localdate()
        self.fields["tarjeta"].queryset = self.fields["tarjeta"].queryset.exclude(
            anio_vencimiento__lt=hoy.year).exclude(anio_vencimiento=hoy.year, mes_vencimiento__lt=hoy.month)
        self.fields["tarjeta"].label_from_instance = lambda t: f"{t} · Saldo COP {number_format(t.saldo, 2, force_grouping=True)}"
        self.fields["referencia"].initial = uuid.uuid4
