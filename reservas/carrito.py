"""Carrito de compras guardado en la sesión del cliente (HU 29).

El carrito solo recuerda qué quiere comprar; no retiene cupos. Los precios, cupos y sillas
se calculan y verifican en el servidor al pagar.
"""
CLAVE = "carrito_tiquetes"


def _serializable(linea):
    return {
        "vuelo": linea["vuelo"], "regreso": linea.get("regreso") or "",
        "viajeros": [{**v, "fecha_nacimiento": v["fecha_nacimiento"].isoformat()
                      if hasattr(v["fecha_nacimiento"], "isoformat") else v["fecha_nacimiento"]} for v in linea["viajeros"]],
    }


def obtener(request):
    return list(request.session.get(CLAVE, []))


def agregar(request, linea):
    lineas = obtener(request)
    lineas.append(_serializable(linea))
    request.session[CLAVE] = lineas


def quitar(request, indice):
    lineas = obtener(request)
    if 0 <= indice < len(lineas):
        del lineas[indice]
    request.session[CLAVE] = lineas


def vaciar(request):
    request.session.pop(CLAVE, None)
