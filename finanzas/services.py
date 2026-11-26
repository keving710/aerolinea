"""Única frontera de escritura financiera. Importes COP, sin red ni cobros reales.

La compra de tiquetes (app `reservas`) pasa su total calculado en servidor y una
referencia UUID dentro de la misma transaction.atomic que confirma los tiquetes.
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


# Reglas simuladas de cada franquicia: longitudes válidas del número y del CVV.
LONGITUDES = {
    Tarjeta.Franquicia.VISA: ((13, 16, 19), 3),
    Tarjeta.Franquicia.MASTERCARD: ((16,), 3),
    Tarjeta.Franquicia.AMEX: ((15,), 4),
    Tarjeta.Franquicia.DINERS: ((14, 15, 16, 17, 18, 19), 3),
    Tarjeta.Franquicia.DISCOVER: ((16, 17, 18, 19), 3),
    Tarjeta.Franquicia.JCB: ((16, 17, 18, 19), 3),
}
FRANQUICIAS_TEXTO = "Visa, Mastercard, American Express, Diners Club, Discover o JCB"


def detectar_franquicia(numero):
    """Franquicia según los primeros dígitos (rangos IIN públicos). None si no se reconoce."""
    p2, p3, p4 = int(numero[:2]), int(numero[:3]), int(numero[:4])
    if numero[0] == "4":
        return Tarjeta.Franquicia.VISA
    if 51 <= p2 <= 55 or 2221 <= p4 <= 2720:
        return Tarjeta.Franquicia.MASTERCARD
    if p2 in (34, 37):
        return Tarjeta.Franquicia.AMEX
    if 300 <= p3 <= 305 or p2 in (36, 38, 39):
        return Tarjeta.Franquicia.DINERS
    if numero.startswith("6011") or 644 <= p3 <= 649 or p2 == 65:
        return Tarjeta.Franquicia.DISCOVER
    if 3528 <= p4 <= 3589:
        return Tarjeta.Franquicia.JCB
    return None


def luhn_valido(numero):
    """Dígito verificador (algoritmo de Luhn) que usan todas las franquicias."""
    total = 0
    for i, d in enumerate(int(c) for c in reversed(numero)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def validar_numero(numero):
    """Devuelve (numero_normalizado, franquicia) o lanza ValidationError."""
    numero = normalizar_numero(numero)
    franquicia = detectar_franquicia(numero)
    if franquicia is None:
        raise ValidationError(f"No reconocemos la franquicia de esta tarjeta. Usa {FRANQUICIAS_TEXTO}.")
    longitudes, _ = LONGITUDES[franquicia]
    if len(numero) not in longitudes:
        raise ValidationError(
            f"Una tarjeta {franquicia.label} debe tener {' o '.join(map(str, longitudes))} dígitos.")
    if not luhn_valido(numero):
        raise ValidationError("El número de tarjeta no es válido: revisa los dígitos.")
    return numero, franquicia


def validar_vencimiento(mes, anio, hoy=None):
    from django.utils import timezone
    hoy = hoy or timezone.localdate()
    try:
        mes, anio = int(mes), int(anio)
    except (TypeError, ValueError):
        raise ValidationError("Ingresa la fecha de vencimiento como MM/AA.")
    if anio < 100:
        anio += 2000
    if not 1 <= mes <= 12:
        raise ValidationError("El mes de vencimiento debe estar entre 01 y 12.")
    if (anio, mes) < (hoy.year, hoy.month):
        raise ValidationError("La tarjeta está vencida.")
    if anio > hoy.year + 20:
        raise ValidationError("La fecha de vencimiento no es válida.")
    return mes, anio


def validar_cvv(cvv, franquicia):
    """El CVV solo se valida (longitud según franquicia); nunca se almacena."""
    franquicia = Tarjeta.Franquicia(franquicia)
    _, largo = LONGITUDES[franquicia]
    if not re.fullmatch(rf"[0-9]{{{largo}}}", str(cvv or "")):
        raise ValidationError(f"El código de seguridad (CVV) de una tarjeta {franquicia.label} tiene {largo} dígitos.")


@transaction.atomic
def registrar_tarjeta(usuario, numero, tipo, saldo, *, mes, anio, cvv):
    _cliente(usuario)
    numero, franquicia = validar_numero(numero)
    mes, anio = validar_vencimiento(mes, anio)
    validar_cvv(cvv, franquicia)
    saldo = importe(saldo, permitir_cero=True)
    if tipo not in Tarjeta.Tipo.values:
        raise ValidationError("Selecciona débito o crédito.")
    huella = salted_hmac("finanzas.tarjeta", numero, algorithm="sha256").hexdigest()
    try:
        with transaction.atomic():
            tarjeta = Tarjeta.objects.create(
                cliente=usuario, tipo=tipo, huella=huella, ultimos_cuatro=numero[-4:], numero_completo=numero,
                franquicia=franquicia, mes_vencimiento=mes, anio_vencimiento=anio)
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
    if tipo != Movimiento.Tipo.REEMBOLSO and tarjeta.vencida:
        # Los reembolsos siempre se aceptan; pagos y recargas no se hacen con tarjetas vencidas.
        raise ValidationError(f"La tarjeta {tarjeta} venció ({tarjeta.vencimiento_texto}). Elige otra tarjeta.")
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


def cobrar(usuario, tarjeta_id, valor, referencia, detalle="Pago simulado"):
    """Descuenta `valor` de la tarjeta. La compra de tiquetes lo llama dentro de su transacción."""
    return _mover(usuario, tarjeta_id, valor, Movimiento.Tipo.COMPRA, referencia, detalle[:160])


def reembolsar(usuario, tarjeta_id, valor, referencia, detalle="Reembolso simulado"):
    """Devuelve `valor` a la tarjeta. Solo lo usan las cancelaciones de la iteración 3 (no hay ruta HTTP)."""
    return _mover(usuario, tarjeta_id, valor, Movimiento.Tipo.REEMBOLSO, referencia, detalle[:160])
