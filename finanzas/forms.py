import uuid
from decimal import Decimal

from django import forms
from django.utils.formats import number_format

from .models import Tarjeta
from .services import normalizar_numero


class TarjetaForm(forms.Form):
    numero = forms.CharField(label="Número de tarjeta ficticia", max_length=25,
                             widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
                             help_text="Solo simulación. No ingreses datos bancarios reales ni CVV.")
    tipo = forms.ChoiceField(label="Tipo de tarjeta", choices=Tarjeta.Tipo.choices)
    saldo = forms.DecimalField(label="Saldo inicial simulado (COP)", min_value=0,
                               max_digits=14, decimal_places=2, initial=0)

    def clean_numero(self):
        return normalizar_numero(self.cleaned_data["numero"])


class OperacionForm(forms.Form):
    tarjeta = forms.ModelChoiceField(label="Tarjeta", queryset=Tarjeta.objects.none())
    valor = forms.DecimalField(label="Valor (COP)", min_value=Decimal("0.01"), max_digits=14, decimal_places=2)
    referencia = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, usuario, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tarjeta"].queryset = Tarjeta.objects.filter(cliente=usuario)
        self.fields["tarjeta"].label_from_instance = lambda t: f"{t} · Saldo COP {number_format(t.saldo, 2, force_grouping=True)}"
        self.fields["referencia"].initial = uuid.uuid4
