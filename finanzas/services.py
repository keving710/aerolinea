"""Única frontera de escritura financiera. Importes COP, sin red ni cobros reales.

La futura compra debe pasar su total calculado en servidor y una referencia UUID
estable dentro de la misma transaction.atomic que confirme sus tiquetes.
"""
import re
import uuid
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils.crypto import salted_hmac

from .models import Movimiento, Tarjeta

MAX_SALDO = Decimal("999999999999.99")


def _cliente(usuario):
    if not usuario.is_authenticated or not usuario.es_cliente:
        raise PermissionDenied("Solo el cliente puede operar su billetera.")


def importe(valor, permitir_cero=False):
    try:
        valor = Decimal(str(valor))
        if (not valor.is_finite() or valor < 0 or (not permitir_cero and valor == 0)
                or valor > MAX_SALDO or valor != valor.quantize(Decimal("0.01"))):
            raise ValueError
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Ingresa un valor válido en COP, con máximo dos decimales.")
    return valor


def normalizar_numero(numero):
    numero = str(numero).replace(" ", "").replace("-", "")
    if not re.fullmatch(r"[0-9]{13,19}", numero):
        raise ValidationError("Ingresa entre 13 y 19 dígitos. Usa únicamente una tarjeta ficticia.")
    return numero


@transaction.atomic
def registrar_tarjeta(usuario, numero, tipo, saldo):
    _cliente(usuario)
    numero = normalizar_numero(numero)
    saldo = importe(saldo, permitir_cero=True)
    if tipo not in Tarjeta.Tipo.values:
        raise ValidationError("Selecciona débito o crédito.")
    huella = salted_hmac("finanzas.tarjeta", numero, algorithm="sha256").hexdigest()
    try:
        with transaction.atomic():
            tarjeta = Tarjeta.objects.create(cliente=usuario, tipo=tipo, huella=huella, ultimos_cuatro=numero[-4:])
    except IntegrityError:
        raise ValidationError("Ya registraste esta tarjeta.")
    if saldo:
        _mover(usuario, tarjeta.pk, saldo, Movimiento.Tipo.RECARGA, uuid.uuid4(), "Saldo inicial simulado")
        tarjeta.refresh_from_db()
    return tarjeta


@transaction.atomic
def _mover(usuario, tarjeta_id, valor, tipo, referencia, detalle):
    _cliente(usuario)
    valor = importe(valor)
    try:
        referencia = uuid.UUID(str(referencia))
    except (ValueError, AttributeError, TypeError):
        raise ValidationError("La referencia de la operación no es válida.")
    tarjeta = get_object_or_404(Tarjeta.objects.select_for_update(), pk=tarjeta_id, cliente=usuario)
    anterior = Movimiento.objects.filter(referencia=referencia).first()
    if anterior:
        if (anterior.tarjeta_id, anterior.tipo, anterior.valor) != (tarjeta.pk, tipo, valor):
            raise ValidationError("La referencia ya fue utilizada para otra operación.")
        return anterior
    qs = Tarjeta.objects.filter(pk=tarjeta.pk, cliente=usuario)
    if tipo == Movimiento.Tipo.COMPRA:
        actualizado = qs.filter(saldo__gte=valor).update(saldo=F("saldo") - valor)
        if not actualizado:
            raise ValidationError("No tienes saldo disponible suficiente. Recarga esta tarjeta o elige otra.")
    else:
        actualizado = qs.filter(saldo__lte=MAX_SALDO - valor).update(saldo=F("saldo") + valor)
        if not actualizado:
            raise ValidationError("La operación excede el saldo máximo permitido.")
    tarjeta.refresh_from_db(fields=["saldo"])
    return Movimiento.objects.create(tarjeta=tarjeta, tipo=tipo, valor=valor,
                                    saldo_resultante=tarjeta.saldo, referencia=referencia, detalle=detalle)


def recargar(usuario, tarjeta_id, valor, referencia):
    return _mover(usuario, tarjeta_id, valor, Movimiento.Tipo.RECARGA, referencia, "Recarga simulada")


def cobrar(usuario, tarjeta_id, valor, referencia):
    return _mover(usuario, tarjeta_id, valor, Movimiento.Tipo.COMPRA, referencia, "Pago simulado")


def reembolsar(usuario, tarjeta_id, valor, referencia):
    # Contrato interno para iteración 3: no se expone como operación HTTP.
    return _mover(usuario, tarjeta_id, valor, Movimiento.Tipo.REEMBOLSO, referencia, "Reembolso simulado")
