# Iteración 3 — Tiquetes aéreos

Fuente funcional: **Historias de Usuario.pdf** (UTP, 29/09/2026). Iteración 3: compra y reserva, cancelaciones, promociones y vuelos realizados (HU 16, 17, 18 y 26–33).

## Trazabilidad

| HU | Entrega | Pruebas |
| --- | --- | --- |
| 26 | Botones Comprar/Reservar en resultados, portada y detalle público. Visitante → registro (vuelve a la compra al terminar); root y administrador → 403 y sin botones | `InicioDesdeResultadosTests` |
| 27 | Formulario por viajero con documento, nombres, apellidos, nacimiento, género, teléfono, correo, contacto y teléfono del contacto, todos obligatorios. Un menor (a la fecha del vuelo) no puede ser el único viajero | `DatosViajerosTests` |
| 28 | `servicios.reservar`: retiene cupos 24 h (nunca más allá de la salida), máx. 5 tiquetes por cliente y vuelo, sin viajero duplicado, liberación automática | `ReservaTests` |
| 29 | Carrito en sesión + `servicios.comprar`: una transacción por compra (reserva, tiquetes, contadores y cobro). Si el pago falla no se compra nada | `CarritoYCompraTests` |
| 30 | Silla aleatoria libre dentro del rango de la clase; índice único parcial en BD por (vuelo, silla) y (vuelo, documento) activos | `ClaseYSillaTests` |
| 31 | Código `RES-` + 8 caracteres aleatorios sin ambiguos, único; correo a cada viajero (un correo por viajero con todos sus tramos) | `ReservaTests` |
| 32 | `servicios.cancelar`: reserva dentro de sus 24 h; compra hasta 1 h antes de la salida, con reintegro a la tarjeta y movimiento en el historial | `CancelacionClienteTests` |
| 33 | `/reservas/`: todas las compras y reservas con estado y estado del check-in (pendiente/completado) | `HistorialTests` |
| 16 | `Vuelo.descuento_porcentaje` (0–90 %) y `costo_vigente`. Aplica aunque haya vendidos (excepción a HU 15); cada tiquete conserva el valor con el que se emitió | `PromocionTests` |
| 17 | `servicios.cancelar_vuelo`: reubica a cada grupo en el vuelo alternativo más cercano de la misma ruta o reintegra; avisa por correo | `CancelarVueloTests` |
| 18 | `servicios.marcar_realizados` y categorías Programados / Realizados / Cancelados | `VuelosRealizadosTests` |

## Decisiones de diseño

* **Modelo.** `Reserva` (código, cliente, estado reservada/comprada/cancelada/vencida, tarjeta de pago) y `Tiquete` (un viajero en un vuelo, tramo ida/regreso, clase, silla, valor emitido, estado y `checkin_completado`, listo para la iteración 4). Un viaje de ida y vuelta es una sola reserva con tiquetes en dos vuelos.
* **Inventario.** Se siguen usando los contadores `tiquetes_vendidos` y `cupos_reservados` de la iteración 2, modificados solo dentro de transacciones y con los vuelos bloqueados en orden fijo (`select_for_update`). La base impide superar la capacidad.
* **Precio.** Una sola tarifa por vuelo (el PDF no define precios por clase). El carrito muestra el valor vigente y el pago exige el total que el cliente vio; si cambió (p. ej. por una promoción) se pide confirmar de nuevo. Una reserva congela el valor con el que se reservó.
* **Ida y vuelta.** El regreso puede ser cualquier vuelo disponible de la ruta inversa que salga después de la llegada de la ida; los viajeros y clases aplican a ambos tramos.
* **Cancelación del cliente.** Cancela toda la reserva. El plazo de una compra se mide contra la salida más próxima de sus tiquetes activos. Se reintegra todo lo pagado por los tiquetes aún activos.
* **Cancelación de un vuelo.** Los tiquetes se agrupan por reserva. Para cada grupo se prueban las alternativas ordenadas por cercanía (misma ruta y tipo, otra fecha u hora, programadas, con cupo para todo el grupo, conservando la clase, sin repetir viajeros ni superar 5 por cliente y sin que un regreso quede antes de su ida). La reubicación no cobra ni devuelve diferencias de precio. Si ninguna sirve, las compras se reintegran a la tarjeta de pago y las reservas sin pago se liberan.
* **Vuelo realizado.** Pasa a «realizado» cuando llega su fecha y hora de salida; las compras se conservan en el histórico.
* **Tareas automáticas sin cron.** `MantenimientoMiddleware` ejecuta el mantenimiento como máximo cada 30 s por proceso y cada operación de compra/reserva libera lo vencido de sus propios vuelos, por lo que la disponibilidad nunca depende de que el proceso haya corrido. También existe `python manage.py mantener_reservas`.
* **Correo.** SMTP si hay `EMAIL_HOST`; si no, se imprime en consola. Un fallo de correo se registra y no revierte la compra.
* **Carrito.** Vive en la sesión del cliente (no retiene cupos; todo se verifica al pagar). Guarda datos de viajeros hasta pagar o quitar.

## Seguridad e integridad

* Solo el rol cliente compra o reserva; el propietario sale de la sesión y toda consulta se limita a él (otro cliente recibe 404).
* Dinero únicamente con `finanzas.services.cobrar/reembolsar` (referencias UUID, `Decimal`, saldo condicionado). Las vistas de cancelación y pago son POST con CSRF.
* Restricciones de BD: silla y viajero únicos por vuelo entre tiquetes activos, estados válidos, reserva vigente con vencimiento, compra con tarjeta, descuento 0–90 %, valor vigente positivo.
* Los datos del carrito no se imprimen en reportes de error (`sensitive_post_parameters`).
* SQLite sirve para desarrollo y pruebas; para concurrencia real usar PostgreSQL (el bloqueo de filas lo aprovecha). No se probó carga concurrente.

## Límites conocidos

* Los vuelos creados con `cargar_vuelos_demo` traen una «ocupación» simulada solo en los contadores (sin tiquetes asociados): reducen cupos, pero no hay pasajeros que reubicar o reintegrar.
* No hay penalizaciones, cambios de fecha ni pago parcial; tampoco check-in ni cambio de silla (iteración 4).
* Vercel no ejecuta tareas programadas en esta configuración; el mantenimiento perezoso cubre el requisito de liberación y realizados.

## Migraciones

* `vuelos/0005_promocion_costo_vigente`: `descuento_porcentaje` y `costo_vigente` (copiado de `costo_persona` en los vuelos existentes) con sus restricciones.
* `reservas/0001_initial`: `Reserva` y `Tiquete`.

## Validación

`python manage.py test`: 246 pruebas (110 nuevas en `reservas/`), incluida la migración con datos previos. Se revisaron además las pantallas de formulario, carrito, detalle e histórico renderizadas en un navegador.

## Datos de prueba para la sustentación

```bash
python manage.py cargar_vuelos_demo --semilla 1   # vuelos de ejemplo (opcional)
python manage.py agregar_regresos                 # un regreso para cada vuelo que no lo tenga (repetible)
python manage.py cargar_clientes_demo             # usuarios, tarjetas, vuelos y reservas de la demo (repetible)
```

Contraseña de todos los usuarios demo: `Demo2026!`

| Usuario | Rol | Para qué sirve |
|---|---|---|
| `admin_demo` | Administrador | HU 16 (promoción) y HU 17 (cancelar vuelo) |
| `cliente_cinco` | Cliente | Ya tiene 5 tiquetes comprados en un vuelo: el 6.º se rechaza |
| `cliente_saldo` | Cliente | Tarjeta con solo $1.000 COP: la compra se rechaza por saldo |
| `cliente_demo` | Cliente | Saldo alto, 2 tiquetes comprados y 1 reserva sin pagar |

Las tarjetas son ficticias y su número se muestra completo en la billetera (el CVV nunca se guarda).
Volver a ejecutar `cargar_clientes_demo` reinicia los datos de la demo.
