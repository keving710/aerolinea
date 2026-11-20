from datetime import datetime

from django import forms
from django.db import transaction
from django.utils import timezone

from . import reglas
from .models import Vuelo, validar_imagen_vuelo

_FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
_HORA = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


def _opciones(ciudades):
    return [("", "Selecciona…")] + [(c, c) for c in ciudades]


def _campo_imagen():
    return forms.ImageField(
        label="Imagen del vuelo", required=False, validators=[validar_imagen_vuelo],
        widget=forms.ClearableFileInput(attrs={"accept": ".jpg,.jpeg,.png,.webp"}),
        help_text="Opcional. JPG, PNG o WEBP de máximo 3 MB. Se muestra en la portada y en la búsqueda; "
                  "si no eliges una, se usa una ilustración según el tipo de vuelo.",
    )


def _calendario_desde_hoy(form, fecha_inicial=True):
    """El calendario arranca en la fecha actual: no deja elegir días pasados y propone hoy."""
    hoy = timezone.localdate()
    for nombre, campo in form.fields.items():
        if nombre.startswith("fecha") and isinstance(campo, forms.DateField):
            campo.widget.attrs["min"] = hoy.isoformat()
    if fecha_inicial and "fecha" in form.fields:
        form.fields["fecha"].initial = hoy


class VueloNacionalForm(forms.Form):
    origen = forms.ChoiceField(label="Origen", choices=_opciones(reglas.CIUDADES_NACIONALES))
    destino = forms.ChoiceField(label="Destino", choices=_opciones(reglas.CIUDADES_NACIONALES))
    fecha = forms.DateField(label="Fecha de salida", widget=_FECHA)
    hora_salida = forms.TimeField(label="Hora de salida", widget=_HORA)
    hora_llegada = forms.TimeField(label="Hora de llegada", widget=_HORA,
                                   help_text="La duración del vuelo se calcula automáticamente.")
    costo_persona = forms.DecimalField(label="Costo por persona (COP)", min_value=1, max_digits=12, decimal_places=2)
    imagen = _campo_imagen()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _calendario_desde_hoy(self)

    def clean(self):
        datos = super().clean()
        o, d = datos.get("origen"), datos.get("destino")
        if o and d and o == d:
            self.add_error("destino", "El origen y el destino no pueden ser la misma ciudad.")
        fecha, hs, hl = datos.get("fecha"), datos.get("hora_salida"), datos.get("hora_llegada")
        if fecha and hs and hl:
            salida = datetime.combine(fecha, hs)
            try:
                minutos, llegada = reglas.duracion_nacional(salida, hl)
            except ValueError as e:
                self.add_error("hora_llegada", str(e))
            else:
                salida_utc = reglas.a_utc(salida, reglas.TZ_COLOMBIA)
                if salida_utc <= timezone.now():
                    self.add_error("fecha", "La salida no puede estar en el pasado.")
                else:
                    datos["_salida_utc"] = salida_utc
                    datos["_llegada_utc"] = reglas.a_utc(llegada, reglas.TZ_COLOMBIA)
                    datos["_minutos"] = minutos
        return datos

    @transaction.atomic
    def crear(self, usuario):
        d = self.cleaned_data
        return Vuelo.objects.create(
            tipo=Vuelo.Tipo.NACIONAL, origen=d["origen"], destino=d["destino"],
            salida=d["_salida_utc"], llegada=d["_llegada_utc"], duracion_minutos=d["_minutos"],
            costo_persona=d["costo_persona"], capacidad=reglas.CAPACIDAD_NACIONAL, creado_por=usuario,
            imagen=d.get("imagen") or None,
        )


def _validar_tramo(form, origen, destino, sufijo, despues_de=None):
    """Valida un tramo internacional (ida o regreso) y deja los cálculos en cleaned_data.

    Si el administrador no escribe la duración, se usa la estimada para la ruta.
    """
    d = form.cleaned_data
    f = lambda n: d.get(n + sufijo)
    fecha, hora, h, m = f("fecha"), f("hora_salida"), f("horas"), f("minutos")
    if None in (fecha, hora):
        return
    if h is None and m is None:
        minutos = reglas.duracion_estimada(origen, destino)
        if minutos is None:
            form.add_error("horas" + sufijo, "Ingresa la duración del vuelo.")
            return
        d["horas" + sufijo], d["minutos" + sufijo] = divmod(minutos, 60)
    else:
        minutos = (h or 0) * 60 + (m or 0)
    if minutos <= 0:
        form.add_error("horas" + sufijo, "La duración debe ser mayor a cero.")
        return
    salida_utc, llegada_utc = reglas.calcular_llegada_internacional(
        datetime.combine(fecha, hora), reglas.zona_de(origen), destino, minutos
    )
    if despues_de is not None:
        if salida_utc <= despues_de:
            form.add_error("fecha" + sufijo, "El regreso debe salir después de la llegada del vuelo de ida.")
            return
    elif salida_utc <= timezone.now():
        form.add_error("fecha" + sufijo, "La salida no puede estar en el pasado.")
        return
    d["_salida" + sufijo] = salida_utc
    d["_llegada" + sufijo] = llegada_utc
    d["_minutos" + sufijo] = minutos


def _campos_tramo(sufijo, etiqueta, requerido):
    ayuda = "Se calcula automáticamente según la ruta; puedes ajustarla."
    return {
        "fecha" + sufijo: forms.DateField(label=f"Fecha de salida{etiqueta}", widget=_FECHA, required=requerido),
        "hora_salida" + sufijo: forms.TimeField(label=f"Hora de salida{etiqueta}", widget=_HORA, required=requerido),
        "horas" + sufijo: forms.IntegerField(label=f"Duración: horas{etiqueta}", min_value=0, max_value=30,
                                             required=False, help_text=ayuda),
        "minutos" + sufijo: forms.IntegerField(label=f"Duración: minutos{etiqueta}", min_value=0, max_value=59,
                                               required=False),
        "costo_persona" + sufijo: forms.DecimalField(
            label=f"Costo por persona (COP){etiqueta}", min_value=1, max_digits=12, decimal_places=2, required=requerido
        ),
    }


def _crear_vuelo(usuario, origen, destino, d, sufijo, ida=None, imagen=None):
    return Vuelo.objects.create(
        tipo=Vuelo.Tipo.INTERNACIONAL, origen=origen, destino=destino,
        salida=d["_salida" + sufijo], llegada=d["_llegada" + sufijo],
        duracion_minutos=d["_minutos" + sufijo], costo_persona=d["costo_persona" + sufijo],
        capacidad=reglas.CAPACIDAD_INTERNACIONAL, creado_por=usuario, vuelo_ida=ida, imagen=imagen,
    )


class VueloInternacionalForm(forms.Form):
    origen = forms.ChoiceField(label="Origen", choices=_opciones(reglas.ORIGENES_INTERNACIONALES))
    destino = forms.ChoiceField(label="Destino", choices=_opciones(reglas.DESTINOS_INTERNACIONALES))
    con_regreso = forms.BooleanField(label="Programar también el vuelo de regreso", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.update(_campos_tramo("", "", True))
        self.fields["imagen"] = _campo_imagen()
        self.fields.update(_campos_tramo("_r", " (regreso)", False))
        # Orden: origen, destino, ida, imagen, checkbox, regreso
        orden = ["origen", "destino", "fecha", "hora_salida", "horas", "minutos", "costo_persona", "imagen",
                 "con_regreso", "fecha_r", "hora_salida_r", "horas_r", "minutos_r", "costo_persona_r"]
        self.order_fields(orden)
        _calendario_desde_hoy(self)

    def clean(self):
        d = super().clean()
        origen, destino = d.get("origen"), d.get("destino")
        if not (origen and destino):
            return d
        _validar_tramo(self, origen, destino, "")
        if d.get("con_regreso"):
            for n in ("fecha", "hora_salida", "costo_persona"):
                if d.get(n + "_r") in (None, ""):
                    self.add_error(n + "_r", "Este campo es obligatorio para el vuelo de regreso.")
            if "_llegada" in d:
                _validar_tramo(self, destino, origen, "_r", despues_de=d["_llegada"])
        return d

    @transaction.atomic
    def crear(self, usuario):
        d = self.cleaned_data
        ida = _crear_vuelo(usuario, d["origen"], d["destino"], d, "", imagen=d.get("imagen") or None)
        regreso = None
        if d.get("con_regreso"):
            # El regreso comparte la imagen de la ida (mismo archivo, sin duplicarlo).
            regreso = _crear_vuelo(usuario, d["destino"], d["origen"], d, "_r", ida=ida,
                                   imagen=ida.imagen.name if ida.imagen else None)
        return ida, regreso


class RegresoForm(forms.Form):
    """Agrega el vuelo de regreso a un vuelo internacional ya creado."""

    def __init__(self, ida, *args, **kwargs):
        self.ida = ida
        super().__init__(*args, **kwargs)
        self.fields.update(_campos_tramo("", "", True))
        self.fields["imagen"] = _campo_imagen()
        self.fields["imagen"].help_text = "Opcional. Si no eliges una, se usa la misma imagen del vuelo de ida."
        _calendario_desde_hoy(self, fecha_inicial=False)
        # Propone como fecha el día en que llega la ida (hora local del destino).
        self.fields["fecha"].initial = timezone.localtime(ida.llegada, reglas.zona_de(ida.destino)).date()

    def clean(self):
        d = super().clean()
        _validar_tramo(self, self.ida.destino, self.ida.origen, "", despues_de=self.ida.llegada)
        return d

    @transaction.atomic
    def crear(self, usuario):
        imagen = self.cleaned_data.get("imagen") or (self.ida.imagen.name if self.ida.imagen else None)
        return _crear_vuelo(usuario, self.ida.destino, self.ida.origen, self.cleaned_data, "", ida=self.ida,
                            imagen=imagen)
