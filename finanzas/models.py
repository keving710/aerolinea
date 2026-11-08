import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Tarjeta(models.Model):
    class Tipo(models.TextChoices):
        DEBITO = "debito", "Débito"
        CREDITO = "credito", "Crédito"

    cliente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tarjetas")
    tipo = models.CharField(max_length=7, choices=Tipo.choices)
    # No se conserva PAN ni CVV: solo una huella HMAC y los últimos cuatro dígitos.
    huella = models.CharField(max_length=64, editable=False)
    ultimos_cuatro = models.CharField(max_length=4, editable=False)
    saldo = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["creada_en", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["cliente", "huella"], name="tarjeta_unica_cliente"),
            models.CheckConstraint(condition=Q(saldo__gte=0), name="tarjeta_saldo_no_negativo"),
            models.CheckConstraint(condition=Q(tipo__in=["debito", "credito"]), name="tarjeta_tipo_valido"),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} •••• {self.ultimos_cuatro}"


class Movimiento(models.Model):
    class Tipo(models.TextChoices):
        RECARGA = "recarga", "Recarga"
        COMPRA = "compra", "Compra simulada"
        REEMBOLSO = "reembolso", "Reembolso"

    tarjeta = models.ForeignKey(Tarjeta, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    valor = models.DecimalField(max_digits=14, decimal_places=2)
    saldo_resultante = models.DecimalField(max_digits=14, decimal_places=2)
    referencia = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    detalle = models.CharField(max_length=160)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(valor__gt=0), name="movimiento_valor_positivo"),
            models.CheckConstraint(condition=Q(saldo_resultante__gte=0), name="movimiento_saldo_no_negativo"),
            models.CheckConstraint(condition=Q(tipo__in=["recarga", "compra", "reembolso"]), name="movimiento_tipo_valido"),
        ]
