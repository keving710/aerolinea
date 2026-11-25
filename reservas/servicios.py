"""Reglas de negocio de compra, reserva y cancelación (HU 16–18 y 26–33).

Toda operación que cambia inventario o dinero vive aquí, dentro de transaction.atomic:
las vistas solo validan formularios y llaman a estas funciones. El cupo de cada vuelo se
controla con los contadores `tiquetes_vendidos` y `cupos_reservados` bajo bloqueo de fila.
"""
import logging
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import EmailMessage, get_connection
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from finanzas import services as finanzas
from vuelos.models import Vuelo

from .models import Reserva, Tiquete

logger = logging.getLogger(__name__)

LIMITE_POR_VUELO = 5
HORAS_RESERVA = 24
ANTICIPO_CANCELACION = timedelta(hours=1)
_azar = random.SystemRandom()


# --------------------------------------------------------------------------
# Mantenimiento: vuelos realizados (HU 18) y reservas vencidas (HU 28)
# --------------------------------------------------------------------------
def marcar_realizados(ahora=None):
    """Pasada la fecha y hora de salida, el vuelo pasa a «realizado» y deja de estar disponible."""
    ahora = ahora or timezone.now()
    return Vuelo.objects.filter(estado=Vuelo.Estado.PROGRAMADO, salida__lte=ahora).update(estado=Vuelo.Estado.REALIZADO)


def _soltar_cupos(tiquetes, reserva_estado):
    """Devuelve al vuelo los cupos de estos tiquetes activos (reservados o vendidos)."""
    por_vuelo = {}
    for t in tiquetes:
        por_vuelo[t.vuelo_id] = por_vuelo.get(t.vuelo_id, 0) + 1
    campo = "cupos_reservados" if reserva_estado == Reserva.Estado.RESERVADA else "tiquetes_vendidos"
    for vuelo_id, cantidad in por_vuelo.items():
        Vuelo.objects.filter(pk=vuelo_id).update(**{campo: F(campo) - cantidad})


def _anular_tiquetes(reserva, motivo):
    activos = list(reserva.tiquetes.filter(estado=Tiquete.Estado.ACTIVO))
    if activos:
        Tiquete.objects.filter(pk__in=[t.pk for t in activos]).update(estado=Tiquete.Estado.CANCELADO, motivo_cancelacion=motivo)
        _soltar_cupos(activos, reserva.estado)
    return activos


def liberar_vencidas(ahora=None, vuelo_ids=None):
    """Libera los cupos de las reservas que superaron su plazo de 24 horas."""
    ahora = ahora or timezone.now()
    pendientes = Reserva.objects.filter(estado=Reserva.Estado.RESERVADA, expira_en__lte=ahora)
    if vuelo_ids:
        pendientes = pendientes.filter(tiquetes__vuelo_id__in=vuelo_ids)
    liberadas = 0
    for pk in sorted(set(pendientes.values_list("pk", flat=True))):
        with transaction.atomic():
            reserva = Reserva.objects.select_for_update().get(pk=pk)
            if reserva.estado != Reserva.Estado.RESERVADA or reserva.expira_en > ahora:
                continue
            _anular_tiquetes(reserva, "Reserva vencida")
            reserva.estado = Reserva.Estado.VENCIDA
            reserva.save(update_fields=["estado"])
            liberadas += 1
    return liberadas


def mantenimiento(ahora=None):
    ahora = ahora or timezone.now()
    return {"realizados": marcar_realizados(ahora), "liberadas": liberar_vencidas(ahora)}


# --------------------------------------------------------------------------
# Validaciones comunes
# --------------------------------------------------------------------------
def _comprador(usuario):
    """Root y administrador no pueden comprar ni reservar (HU 28 y 29)."""
    if not usuario.is_authenticated or not usuario.es_cliente:
        raise PermissionDenied("Solo el cliente puede comprar o reservar tiquetes.")


def edad_en(fecha_nacimiento, fecha):
    return fecha.year - fecha_nacimiento.year - ((fecha.month, fecha.day) < (fecha_nacimiento.month, fecha_nacimiento.day))


def validar_menores(viajeros, fecha_viaje):
    """Un menor de edad no puede ser el único viajero (HU 27)."""
    if viajeros and all(edad_en(v["fecha_nacimiento"], fecha_viaje) < 18 for v in viajeros):
        raise ValidationError("Un menor de edad no puede viajar solo: incluye al menos un viajero mayor de edad.")


def validar_regreso(ida, regreso):
    if (ida.origen, ida.destino) != (regreso.destino, regreso.origen):
        raise ValidationError("El vuelo de regreso debe ir del destino al origen del vuelo de ida.")
    if regreso.salida <= ida.llegada:
        raise ValidationError("El vuelo de regreso debe salir después de la llegada del vuelo de ida.")


def _validar_tramo(cliente, vuelo, viajeros, ahora, previos=()):
    """`previos`: documentos de otras líneas del carrito que ya apartan sillas en este mismo vuelo."""
    if vuelo.estado != Vuelo.Estado.PROGRAMADO or vuelo.salida <= ahora:
        raise ValidationError(f"El vuelo {vuelo.codigo} ya no está disponible.")
    n = len(viajeros)
    if not 1 <= n <= LIMITE_POR_VUELO:
        raise ValidationError(f"Puedes comprar o reservar entre 1 y {LIMITE_POR_VUELO} tiquetes por vuelo.")
    propios = Tiquete.objects.filter(vuelo=vuelo, estado=Tiquete.Estado.ACTIVO, reserva__cliente=cliente).count() + len(previos)
    if propios + n > LIMITE_POR_VUELO:
        restantes = max(0, LIMITE_POR_VUELO - propios)
        raise ValidationError(
            f"Máximo {LIMITE_POR_VUELO} tiquetes por vuelo y cliente: en {vuelo.codigo} ya tienes {propios}"
            f" y solo puedes agregar {restantes} más.")
    documentos = [v["documento"] for v in viajeros]
    if len(set(documentos)) != len(documentos):
        raise ValidationError("Un mismo viajero no puede repetirse en el mismo vuelo.")
    repetidos = list(Tiquete.objects.filter(vuelo=vuelo, estado=Tiquete.Estado.ACTIVO, documento__in=documentos)
                     .values_list("documento", flat=True)) + [d for d in documentos if d in previos]
    if repetidos:
        raise ValidationError(f"El viajero con documento {repetidos[0]} ya tiene un tiquete en el vuelo {vuelo.codigo}.")
    if vuelo.cupos_disponibles < n + len(previos):
        raise ValidationError(f"El vuelo {vuelo.codigo} no tiene cupos suficientes: quedan {vuelo.cupos_disponibles}.")
    validar_menores(viajeros, timezone.localtime(vuelo.salida, vuelo.zona_origen).date())


def _asignar_sillas(vuelo, clases, ocupadas=None):
    """Silla aleatoria dentro del rango de cada clase y libre en el vuelo (HU 30)."""
    if ocupadas is None:
        ocupadas = set(Tiquete.objects.filter(vuelo=vuelo, estado=Tiquete.Estado.ACTIVO).values_list("silla", flat=True))
    sillas = []
    for clase in clases:
        inicio, fin = vuelo.rango_clase(clase)
        libres = [s for s in range(inicio, fin + 1) if s not in ocupadas]
        if not libres:
            raise ValidationError(f"No quedan sillas de {Tiquete.Clase(clase).label.lower()} en el vuelo {vuelo.codigo}.")
        silla = _azar.choice(libres)
        ocupadas.add(silla)
        sillas.append(silla)
    return sillas


def _bloquear(ids):
    """Bloquea los vuelos en orden fijo (evita interbloqueos) y libera reservas vencidas de ellos."""
    ids = sorted(set(ids))
    list(Vuelo.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    liberar_vencidas(vuelo_ids=ids)
    return {v.pk: v for v in Vuelo.objects.filter(pk__in=ids)}


# --------------------------------------------------------------------------
# Compra y reserva (HU 28, 29, 30)
# --------------------------------------------------------------------------
def tramos_de_linea(linea):
    """[(vuelo, viajeros)] a partir de una línea {vuelo, regreso, viajeros}."""
    ida = Vuelo.objects.filter(codigo=linea["vuelo"]).first()
    if ida is None:
        raise ValidationError("El vuelo seleccionado ya no existe.")
    tramos = [(ida, Tiquete.Tramo.IDA)]
    if linea.get("regreso"):
        regreso = Vuelo.objects.filter(codigo=linea["regreso"]).first()
        if regreso is None:
            raise ValidationError("El vuelo de regreso seleccionado ya no existe.")
        validar_regreso(ida, regreso)
        tramos.append((regreso, Tiquete.Tramo.REGRESO))
    viajeros = [{**v, "fecha_nacimiento": date.fromisoformat(v["fecha_nacimiento"])
                 if isinstance(v["fecha_nacimiento"], str) else v["fecha_nacimiento"]} for v in linea["viajeros"]]
    return [(v, tramo, viajeros) for v, tramo in tramos]


def _emitir(cliente, linea, estado, tarjeta=None):
    """Crea la reserva o compra de una línea. Debe llamarse dentro de transaction.atomic."""
    _comprador(cliente)
    ahora = timezone.now()
    tramos = tramos_de_linea(linea)
    vuelos = _bloquear(v.pk for v, _, _ in tramos)
    tramos = [(vuelos[v.pk], tramo, viajeros) for v, tramo, viajeros in tramos]
    for vuelo, _, viajeros in tramos:
        _validar_tramo(cliente, vuelo, viajeros, ahora)

    reserva = Reserva.objects.create(
        cliente=cliente, estado=estado, tarjeta=tarjeta,
        trayecto=Reserva.Trayecto.COMPLETO if len(tramos) == 2 else Reserva.Trayecto.UNICO,
        expira_en=(min(ahora + timedelta(hours=HORAS_RESERVA), min(v.salida for v, _, _ in tramos))
                   if estado == Reserva.Estado.RESERVADA else None),
        pagada_en=ahora if estado == Reserva.Estado.COMPRADA else None,
    )
    total = Decimal(0)
    campo = "tiquetes_vendidos" if estado == Reserva.Estado.COMPRADA else "cupos_reservados"
    for vuelo, tramo, viajeros in tramos:
        sillas = _asignar_sillas(vuelo, [v["clase"] for v in viajeros])
        for datos, silla in zip(viajeros, sillas):
            Tiquete.objects.create(
                reserva=reserva, vuelo=vuelo, tramo=tramo, silla=silla, valor=vuelo.costo_vigente,
                **{k: datos[k] for k in ("clase", "documento", "nombres", "apellidos", "fecha_nacimiento", "genero",
                                         "telefono", "correo", "contacto_nombre", "contacto_telefono")})
            total += vuelo.costo_vigente
        Vuelo.objects.filter(pk=vuelo.pk).update(**{campo: F(campo) + len(viajeros)})
    if estado == Reserva.Estado.COMPRADA:
        # Si el pago no se valida (saldo insuficiente, tarjeta vencida...) se revierte toda la compra.
        finanzas.cobrar(cliente, tarjeta.pk, total, uuid.uuid4(), f"Compra de tiquetes {reserva.codigo}")
    return reserva


def _con_reintento(funcion):
    try:
        with transaction.atomic():
            return funcion()
    except IntegrityError:
        raise ValidationError("Otra operación tomó esas sillas o cupos al mismo tiempo. Inténtalo de nuevo.")


def reservar(cliente, linea):
    """Reserva (HU 28): retiene los cupos 24 horas sin pago inmediato."""
    reserva = _con_reintento(lambda: _emitir(cliente, linea, Reserva.Estado.RESERVADA))
    notificar_confirmacion(reserva)
    return reserva


def comprar(cliente, lineas, tarjeta):
    """Compra todo el carrito con una tarjeta (HU 29); todo se confirma o nada se confirma."""
    if not lineas:
        raise ValidationError("Tu carrito está vacío.")
    _comprador(cliente)

    def operacion():
        return [_emitir(cliente, linea, Reserva.Estado.COMPRADA, tarjeta) for linea in lineas]

    reservas = _con_reintento(operacion)
    for reserva in reservas:
        notificar_confirmacion(reserva)
    return reservas


def validar_linea(cliente, linea, otras_lineas=()):
    """Valida una línea al agregarla al carrito, contando lo que ya hay en él. No bloquea ni escribe."""
    _comprador(cliente)
    liberar_vencidas()
    previos = {}
    for otra in otras_lineas:
        for vuelo, _, viajeros in tramos_de_linea(otra):
            previos.setdefault(vuelo.codigo, []).extend(v["documento"] for v in viajeros)
    ahora = timezone.now()
    for vuelo, _, viajeros in tramos_de_linea(linea):
        _validar_tramo(cliente, vuelo, viajeros, ahora, previos.get(vuelo.codigo, ()))


def total_linea(linea):
    """Valor actual de una línea del carrito (sirve para mostrarla y para validar el pago)."""
    return sum((v.costo_vigente * len(viajeros) for v, _, viajeros in tramos_de_linea(linea)), Decimal(0))


def pagar_reserva(cliente, reserva_id, tarjeta):
    """Convierte una reserva vigente en compra, con el valor con el que se reservó."""
    _comprador(cliente)

    def operacion():
        reserva = Reserva.objects.select_for_update().get(pk=reserva_id, cliente=cliente)
        ahora = timezone.now()
        if reserva.estado != Reserva.Estado.RESERVADA:
            raise ValidationError("Solo se pueden pagar reservas vigentes.")
        if reserva.expira_en <= ahora:
            liberar_vencidas(ahora)
            raise ValidationError("La reserva venció y sus cupos fueron liberados.")
        activos = list(reserva.tiquetes.filter(estado=Tiquete.Estado.ACTIVO).select_related("vuelo"))
        vuelos = _bloquear(t.vuelo_id for t in activos)
        for t in activos:
            if vuelos[t.vuelo_id].estado != Vuelo.Estado.PROGRAMADO or vuelos[t.vuelo_id].salida <= ahora:
                raise ValidationError(f"El vuelo {t.vuelo.codigo} ya no está disponible.")
        total = sum((t.valor for t in activos), Decimal(0))
        reserva.refresh_from_db()
        if reserva.estado != Reserva.Estado.RESERVADA:
            raise ValidationError("La reserva venció y sus cupos fueron liberados.")
        finanzas.cobrar(cliente, tarjeta.pk, total, uuid.uuid4(), f"Pago de la reserva {reserva.codigo}")
        for vuelo_id, cantidad in _contar_por_vuelo(activos).items():
            Vuelo.objects.filter(pk=vuelo_id).update(cupos_reservados=F("cupos_reservados") - cantidad,
                                                     tiquetes_vendidos=F("tiquetes_vendidos") + cantidad)
        reserva.estado, reserva.tarjeta, reserva.pagada_en, reserva.expira_en = (
            Reserva.Estado.COMPRADA, tarjeta, ahora, None)
        reserva.save(update_fields=["estado", "tarjeta", "pagada_en", "expira_en"])
        return reserva

    reserva = _con_reintento(operacion)
    notificar_confirmacion(reserva)
    return reserva


def _contar_por_vuelo(tiquetes):
    cuentas = {}
    for t in tiquetes:
        cuentas[t.vuelo_id] = cuentas.get(t.vuelo_id, 0) + 1
    return cuentas


# --------------------------------------------------------------------------
# Cancelación por el cliente (HU 32)
# --------------------------------------------------------------------------
def motivo_no_cancelable(reserva, ahora=None):
    """Texto con el motivo por el que no se puede cancelar, o '' si se puede."""
    ahora = ahora or timezone.now()
    if reserva.estado == Reserva.Estado.RESERVADA:
        if reserva.expira_en <= ahora:
            return "La reserva ya venció: pasaron las 24 horas para cancelarla."
        return ""
    if reserva.estado == Reserva.Estado.COMPRADA:
        activos = reserva.tiquetes_activos
        if not activos:
            return "La compra no tiene tiquetes activos."
        primero = min(t.vuelo.salida for t in activos)
        if ahora > primero - ANTICIPO_CANCELACION:
            limite = min(activos, key=lambda t: t.vuelo.salida).vuelo
            return ("Las compras solo se pueden cancelar hasta 1 hora antes del vuelo "
                    f"(el plazo para {limite.codigo} terminó).")
        return ""
    return f"La reserva ya está {reserva.get_estado_display().lower()}."


def cancelar(cliente, reserva_id):
    """Cancela una compra o reserva propia: libera cupos y, si hubo pago, reintegra el dinero."""
    _comprador(cliente)

    def operacion():
        reserva = Reserva.objects.select_for_update().get(pk=reserva_id, cliente=cliente)
        _bloquear(reserva.tiquetes.values_list("vuelo_id", flat=True))
        reserva.refresh_from_db()
        ahora = timezone.now()
        motivo = motivo_no_cancelable(reserva, ahora)
        if motivo:
            raise ValidationError(motivo)
        estado_previo = reserva.estado
        activos = _anular_tiquetes(reserva, "Cancelado por el cliente")
        reintegro = Decimal(0)
        if estado_previo == Reserva.Estado.COMPRADA:
            reintegro = sum((t.valor for t in activos), Decimal(0))
            finanzas.reembolsar(cliente, reserva.tarjeta_id, reintegro, uuid.uuid4(), f"Reintegro por cancelar {reserva.codigo}")
        reserva.estado, reserva.cancelada_en = Reserva.Estado.CANCELADA, ahora
        reserva.save(update_fields=["estado", "cancelada_en"])
        return reserva, reintegro

    return _con_reintento(operacion)


# --------------------------------------------------------------------------
# Cancelación de un vuelo por el administrador (HU 17)
# --------------------------------------------------------------------------
def alternativas_para(vuelo, ahora=None):
    """Vuelos de la misma ruta, programados, en otra fecha u hora, ordenados por cercanía."""
    ahora = ahora or timezone.now()
    candidatos = (Vuelo.objects.filter(estado=Vuelo.Estado.PROGRAMADO, salida__gt=ahora, tipo=vuelo.tipo,
                                       origen=vuelo.origen, destino=vuelo.destino)
                  .exclude(pk=vuelo.pk).exclude(salida=vuelo.salida))
    return sorted(candidatos, key=lambda v: (abs(v.salida - vuelo.salida), v.pk))


def _otro_tramo(reserva, tiquetes):
    """Vuelo del otro tramo (ida o regreso) de la misma reserva, si lo hay y sigue activo."""
    tramo = tiquetes[0].tramo
    otro = reserva.tiquetes.filter(estado=Tiquete.Estado.ACTIVO).exclude(tramo=tramo).select_related("vuelo").first()
    return otro.vuelo if otro else None


def _intentar_reubicar(reserva, tiquetes, alt):
    """Mueve el grupo de tiquetes al vuelo alternativo si cumple todas las reglas; si no, devuelve False."""
    n = len(tiquetes)
    if alt.cupos_disponibles < n:
        return False
    otro = _otro_tramo(reserva, tiquetes)
    if otro is not None:
        ida_regreso = (alt, otro) if tiquetes[0].tramo == Tiquete.Tramo.IDA else (otro, alt)
        if ida_regreso[1].salida <= ida_regreso[0].llegada:
            return False
    propios = Tiquete.objects.filter(vuelo=alt, estado=Tiquete.Estado.ACTIVO, reserva__cliente=reserva.cliente).count()
    if propios + n > LIMITE_POR_VUELO:
        return False
    documentos = [t.documento for t in tiquetes]
    if Tiquete.objects.filter(vuelo=alt, estado=Tiquete.Estado.ACTIVO, documento__in=documentos).exists():
        return False
    try:
        sillas = _asignar_sillas(alt, [t.clase for t in tiquetes])
    except ValidationError:
        return False
    origen = tiquetes[0].vuelo
    for t, silla in zip(tiquetes, sillas):
        t.vuelo, t.silla, t.reubicado_desde = alt, silla, origen
        t.save(update_fields=["vuelo", "silla", "reubicado_desde"])
    campo = "cupos_reservados" if reserva.estado == Reserva.Estado.RESERVADA else "tiquetes_vendidos"
    Vuelo.objects.filter(pk=origen.pk).update(**{campo: F(campo) - n})
    Vuelo.objects.filter(pk=alt.pk).update(**{campo: F(campo) + n})
    setattr(alt, campo, getattr(alt, campo) + n)
    if reserva.estado == Reserva.Estado.RESERVADA and reserva.expira_en > alt.salida:
        reserva.expira_en = alt.salida
        reserva.save(update_fields=["expira_en"])
    return True


def cancelar_vuelo(admin, vuelo_id):
    """Cancela un vuelo: cada viajero se reubica en otro vuelo de la ruta o recibe su reintegro.

    Devuelve un resumen con los tiquetes reubicados, reintegrados y liberados sin pago.
    """
    if not admin.is_authenticated or not admin.es_administrador:
        raise PermissionDenied("Solo el administrador puede cancelar vuelos.")
    resumen = {"reubicados": 0, "reintegrados": 0, "liberados": 0, "valor_reintegrado": Decimal(0)}
    avisos = []

    def operacion():
        ahora = timezone.now()
        vuelo = Vuelo.objects.select_for_update().get(pk=vuelo_id)
        motivo = vuelo.motivo_no_modificable
        if motivo:
            raise ValidationError(motivo)
        liberar_vencidas(ahora)
        vuelo.estado = Vuelo.Estado.CANCELADO
        vuelo.save(update_fields=["estado"])
        alternativas = list(Vuelo.objects.select_for_update().filter(pk__in=[v.pk for v in alternativas_para(vuelo, ahora)]))
        alternativas.sort(key=lambda v: (abs(v.salida - vuelo.salida), v.pk))
        grupos = {}
        for t in (Tiquete.objects.filter(vuelo=vuelo, estado=Tiquete.Estado.ACTIVO)
                  .select_related("reserva", "reserva__cliente").order_by("pk")):
            grupos.setdefault(t.reserva_id, []).append(t)
        for reserva_id, tiquetes in grupos.items():
            reserva = Reserva.objects.select_for_update().get(pk=reserva_id)
            if any(_intentar_reubicar(reserva, tiquetes, alt) for alt in alternativas):
                resumen["reubicados"] += len(tiquetes)
                avisos.append((reserva, tiquetes, "reubicado"))
                continue
            Tiquete.objects.filter(pk__in=[t.pk for t in tiquetes]).update(
                estado=Tiquete.Estado.CANCELADO, motivo_cancelacion=f"Vuelo {vuelo.codigo} cancelado")
            _soltar_cupos(tiquetes, reserva.estado)
            if reserva.estado == Reserva.Estado.COMPRADA:
                valor = sum((t.valor for t in tiquetes), Decimal(0))
                finanzas.reembolsar(reserva.cliente, reserva.tarjeta_id, valor, uuid.uuid4(),
                                    f"Reintegro: vuelo {vuelo.codigo} cancelado ({reserva.codigo})")
                resumen["reintegrados"] += len(tiquetes)
                resumen["valor_reintegrado"] += valor
                avisos.append((reserva, tiquetes, "reintegrado"))
            else:
                resumen["liberados"] += len(tiquetes)
                avisos.append((reserva, tiquetes, "liberado"))
            if not reserva.tiquetes.filter(estado=Tiquete.Estado.ACTIVO).exists():
                reserva.estado, reserva.cancelada_en = Reserva.Estado.CANCELADA, ahora
                reserva.save(update_fields=["estado", "cancelada_en"])
        return vuelo

    vuelo = _con_reintento(operacion)
    for reserva, tiquetes, accion in avisos:
        notificar_cambio(vuelo, reserva, tiquetes, accion)
    return resumen


# --------------------------------------------------------------------------
# Correo electrónico (HU 31)
# --------------------------------------------------------------------------
def _linea_tiquete(t):
    return (f"  {t.get_tramo_display()}: {t.vuelo.codigo} · {t.vuelo.origen} → {t.vuelo.destino}\n"
            f"    Salida: {t.vuelo.salida_local} (hora de {t.vuelo.origen})\n"
            f"    Llegada: {t.vuelo.llegada_local} (hora de {t.vuelo.destino})\n"
            f"    {t.get_clase_display()} · silla {t.silla}")


def _enviar(mensajes):
    """Envía sin interrumpir la operación si el correo falla. Devuelve cuántos se enviaron."""
    if not mensajes:
        return 0
    try:
        return get_connection().send_messages(mensajes) or 0
    except Exception:  # pragma: no cover - depende del servidor de correo
        logger.exception("No se pudieron enviar los correos de la reserva")
        return 0


def notificar_confirmacion(reserva):
    """Envía el código de reserva al correo de cada viajero de la compra o reserva."""
    por_viajero = {}
    for t in reserva.tiquetes.filter(estado=Tiquete.Estado.ACTIVO).select_related("vuelo").order_by("tramo", "pk"):
        por_viajero.setdefault(t.documento, []).append(t)
    es_compra = reserva.estado == Reserva.Estado.COMPRADA
    mensajes = []
    for tiquetes in por_viajero.values():
        t0 = tiquetes[0]
        cuerpo = [f"Hola {t0.nombres},", "",
                  f"Tu {'compra' if es_compra else 'reserva'} quedó confirmada.", "",
                  f"Código de reserva: {reserva.codigo}", "", "Tu viaje:"]
        cuerpo += [_linea_tiquete(t) for t in tiquetes]
        if not es_compra and reserva.expira_en:
            fin = timezone.localtime(reserva.expira_en).strftime("%d/%m/%Y %H:%M")
            cuerpo += ["", f"Tus cupos se retienen hasta el {fin}. Si no compras antes, se liberan automáticamente."]
        cuerpo += ["", "Guarda este código: lo necesitarás para tu check-in.", "", "Tiquetes aéreos"]
        mensajes.append(EmailMessage(f"Tu {'compra' if es_compra else 'reserva'} {reserva.codigo}", "\n".join(cuerpo), to=[t0.correo]))
    return _enviar(mensajes)


def notificar_cambio(vuelo, reserva, tiquetes, accion):
    textos = {
        "reubicado": "Te reubicamos en otro vuelo de la misma ruta, sin costo adicional.",
        "reintegrado": "No había un vuelo alternativo disponible: devolvimos el dinero a la tarjeta con la que pagaste.",
        "liberado": "Tu reserva para este vuelo se liberó porque no había un vuelo alternativo disponible.",
    }
    mensajes = []
    for t in tiquetes:
        t.refresh_from_db()
        cuerpo = [f"Hola {t.nombres},", "", f"El vuelo {vuelo.codigo} ({vuelo.origen} → {vuelo.destino}) fue cancelado.",
                  textos[accion], "", f"Código de reserva: {reserva.codigo}"]
        if accion == "reubicado":
            cuerpo += ["", "Tu nuevo vuelo:", _linea_tiquete(t)]
        mensajes.append(EmailMessage(f"Cambio en tu reserva {reserva.codigo}", "\n".join(cuerpo), to=[t.correo]))
    return _enviar(mensajes)
