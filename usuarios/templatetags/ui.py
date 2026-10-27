from django import template

register = template.Library()

ANCHO_COMPLETO = {"direccion_facturacion", "email", "foto", "con_regreso", "costo_persona", "costo_persona_r"}
ENCABEZADOS = {"con_regreso": "Vuelo de regreso"}


@register.filter
def bs(campo):
    """Dibuja el campo con las clases de Bootstrap (y marca los errores)."""
    widget = campo.field.widget
    tipo = getattr(widget, "input_type", "")
    if tipo == "checkbox":
        clase = "form-check-input"
    elif tipo == "select":
        clase = "form-select"
    else:
        clase = "form-control"
    if campo.errors:
        clase += " is-invalid"
    return campo.as_widget(attrs={"class": clase})


@register.filter
def ancho(campo):
    """Columna que ocupa el campo: completa o media fila."""
    tipo = getattr(campo.field.widget, "input_type", "")
    if campo.name in ANCHO_COMPLETO or tipo in ("checkbox", "file"):
        return "col-12"
    return "col-md-6"


@register.filter
def encabezado(campo):
    return ENCABEZADOS.get(campo.name, "")


@register.filter
def es_checkbox(campo):
    return getattr(campo.field.widget, "input_type", "") == "checkbox"
