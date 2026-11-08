from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from . import reglas
from .forms import VueloInternacionalForm, VueloNacionalForm, _opciones
from .models import Vuelo


class BusquedaForm(forms.Form):
    ciudades = sorted(set(reglas.CIUDADES_NACIONALES + reglas.DESTINOS_INTERNACIONALES))
    origen = forms.ChoiceField(label="Origen", choices=[("", "Cualquier origen")] + [(c, c) for c in ciudades], required=False)
    destino = forms.ChoiceField(label="Destino", choices=[("", "Cualquier destino")] + [(c, c) for c in ciudades], required=False)
    fecha = forms.DateField(label="Fecha de salida (hora del origen)", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    tipo = forms.ChoiceField(label="Tipo de vuelo", choices=[("", "Todos")] + list(Vuelo.Tipo.choices), required=False)
    codigo = forms.CharField(label="Código de vuelo", max_length=12, required=False)
    hora = forms.TimeField(label="Hora de salida (hora del origen)", required=False, widget=forms.TimeInput(attrs={"type": "time"}))
    duracion_min = forms.IntegerField(label="Duración mínima (minutos)", min_value=1, required=False)
    duracion_max = forms.IntegerField(label="Duración máxima (minutos)", min_value=1, required=False)
    costo_min = forms.DecimalField(label="Costo mínimo (COP)", min_value=0, max_digits=12, decimal_places=2, required=False)
    costo_max = forms.DecimalField(label="Costo máximo (COP)", min_value=0, max_digits=12, decimal_places=2, required=False)
    orden = forms.ChoiceField(label="Ordenar por", required=False, choices=[("salida", "Próxima salida"),
                              ("costo_persona", "Menor precio"), ("duracion_minutos", "Menor duración")])

    def clean(self):
        d = super().clean()
        for campo in ("costo", "duracion"):
            minimo, maximo = d.get(campo + "_min"), d.get(campo + "_max")
            if minimo is not None and maximo is not None and minimo > maximo:
                self.add_error(campo + "_max", "El máximo debe ser mayor o igual al mínimo.")
        if d.get("origen") and d.get("origen") == d.get("destino"):
            self.add_error("destino", "El origen y el destino deben ser distintos.")
        return d


def formulario_edicion(vuelo, data=None):
    salida = timezone.localtime(vuelo.salida, vuelo.zona_origen)
    initial = {"origen": vuelo.origen, "destino": vuelo.destino, "fecha": salida.date(),
               "hora_salida": salida.time().replace(tzinfo=None), "costo_persona": vuelo.costo_persona}
    if vuelo.tipo == Vuelo.Tipo.NACIONAL:
        initial["hora_llegada"] = timezone.localtime(vuelo.llegada, vuelo.zona_destino).time().replace(tzinfo=None)
        return VueloNacionalForm(data, initial=initial)
    initial.update(horas=vuelo.duracion_minutos // 60, minutos=vuelo.duracion_minutos % 60)
    form = VueloInternacionalForm(data, initial=initial)
    for campo in list(form.fields):
        if campo == "con_regreso" or campo.endswith("_r"):
            del form.fields[campo]
    if vuelo.es_regreso:
        form.fields["origen"].choices = _opciones(reglas.DESTINOS_INTERNACIONALES)
        form.fields["destino"].choices = _opciones(reglas.ORIGENES_INTERNACIONALES)
    return form


def validar_vinculos(vuelo):
    if vuelo.es_regreso:
        ida = vuelo.vuelo_ida
        regreso = vuelo
    elif hasattr(vuelo, "vuelo_regreso"):
        ida, regreso = vuelo, vuelo.vuelo_regreso
    else:
        return
    if (ida.origen, ida.destino) != (regreso.destino, regreso.origen):
        raise ValidationError("La ruta debe conservar la correspondencia con el vuelo vinculado de ida o regreso.")
    if regreso.salida <= ida.llegada:
        raise ValidationError("El regreso debe salir después de la llegada del vuelo de ida.")
