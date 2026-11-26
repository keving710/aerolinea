from django import forms


class PromocionForm(forms.Form):
    """Parámetro editable de la promoción sobre el valor unitario (HU 16)."""

    descuento = forms.DecimalField(
        label="Descuento sobre el valor por persona (%)", min_value=0, max_value=90, max_digits=5, decimal_places=2,
        help_text="De 0 a 90. Usa 0 para quitar la promoción.")


class CancelarVueloForm(forms.Form):
    confirmar = forms.BooleanField(
        label="Entiendo que cancelar el vuelo reubica o reintegra a todos sus pasajeros y no se puede deshacer",
        error_messages={"required": "Marca la casilla para confirmar la cancelación."})
