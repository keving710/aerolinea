# Iteración 2 — Tiquetes aéreos

Fuente funcional: **Historias de Usuario.pdf**, UTP, 29/09/2026. Se revisaron los criterios y los mockups de las páginas 11, 17, 21, 26–27 y 36–41. Se conserva el lenguaje visual Bootstrap de la iteración 1 y se añaden ilustraciones locales de vuelos.

## Trazabilidad

| HU | Entrega y ruta | Verificación automatizada |
| --- | --- | --- |
| 9 | `/billetera/`: panel individual, saldo total y tarjetas propias | Aislamiento por propietario, autenticación, rol y respuestas privadas |
| 15 | `/vuelos/<codigo>/editar/`: edición nacional e internacional | Solo administrador; bloqueo de vendidos, realizados, iniciados y cancelados; validación de rutas, precios, horarios y vínculos |
| 19 | `/`: próximos vuelos con ilustración, código, ruta, horarios, duración, precio y cupos; enlace a catálogo completo | Portada y detalle público sin datos privados del creador |
| 24 | `/vuelos/buscar/`: código parcial, origen, destino, fecha, hora, tipo, rangos de duración y costo; orden y paginación | Criterios independientes y combinados, filtros inválidos, zonas horarias y regresos |
| 25 | Catálogo compartido por portada, búsqueda y detalle | Exclusión de cancelados, realizados, pasados, vendidos y reservados sin cupos |
| 34 | `/billetera/tarjetas/nueva/`: varias tarjetas débito/crédito con saldo inicial | Números ficticios de 13–19 dígitos, tipos, saldos, duplicados normalizados, propietario asignado en servidor |
| 35 | `/billetera/recargar/`: recarga e historial en una transacción | Saldo anterior + recarga, reintentos idempotentes, límites y rollback |
| 36 | Panel con saldo por tarjeta y total agregado | Saldos actualizados y sin exposición de tarjetas ajenas |
| 37 | Servicio de cobro/reembolso y formulario de pago simulado | Fondos suficientes, saldo exacto, cero permitido, insuficiencia sin movimiento y rollback |
| 38 | `/billetera/simular-pago/`: selección explícita de tarjeta propia | Descuento solo en la tarjeta elegida, rechazo de tarjeta ajena |
| 39 | Historial paginado en `/billetera/` | Tipo, valor, fecha, tarjeta, detalle y saldo resultante; recargas, compras simuladas y reembolsos |

## Alcance de la simulación

El simulador permite probar HU 37 y 38 ingresando un importe y seleccionando una tarjeta. Registra un **pago simulado**, sin emitir, comprar ni reservar tiquetes. No hay proveedor de pagos, datos de CVV, llamadas bancarias, promociones ni cancelaciones. Los reembolsos se verifican a través del servicio interno, sin una ruta que permita al cliente crear devoluciones arbitrarias.

Para la iteración 3 quedan los flujos de compra/reserva, cálculo del total de tiquetes, cancelaciones y promociones. Sus contratos mínimos están preparados:

* `finanzas.services.cobrar(usuario, tarjeta_id, valor, referencia)` y `reembolsar(...)` reciben importes calculados por el servidor y una referencia UUID estable por operación. La confirmación de tiquetes y el movimiento deben integrarse en una misma `transaction.atomic()`.
* `Vuelo.tiquetes_vendidos` y `cupos_reservados` son contadores internos, no editables desde formularios ni desde Django Admin. Cupos = capacidad − vendidos − reservados. La base impide superar la capacidad. La futura lógica de inventario debe bloquear el vuelo, mantener los contadores en la transacción de compra/reserva y conservar la regla de bloqueo si hubo ventas históricas al añadir cancelaciones.

## Seguridad e integridad

* Todas las operaciones financieras requieren rol cliente. El propietario proviene de la sesión y todas las consultas están limitadas a él, incluso cuando se manipulan identificadores enviados por POST.
* Solo se guardan los últimos cuatro dígitos y una huella HMAC-SHA256 del número normalizado. No se conserva el número completo ni CVV. Los errores no vuelven a mostrar el número y se marca como dato sensible para los reportes de Django. Usar únicamente datos ficticios. La huella depende de `SECRET_KEY`: conservar esta clave; su rotación requiere planificar la deduplicación de tarjetas ya existentes.
* Importes `Decimal` con dos decimales, límites máximos, saldo no negativo y transacciones que incluyen el historial. Actualizaciones condicionales `F()` impiden gastar fondos inexistentes; bloqueo por tarjeta en PostgreSQL y referencia única evitan duplicar una operación reintentada.
* SQLite sirve para desarrollo y pruebas. Bajo escrituras simultáneas puede responder con bloqueo de base de datos; para concurrencia real se debe usar PostgreSQL. No se ha certificado una carga concurrente de producción en este entorno.
* GET no modifica saldos. POST protegido con CSRF y patrón POST/redirect/GET. Las páginas financieras envían `Cache-Control: no-store`. No se exponen estos modelos financieros en Django Admin.
* La edición de vuelos bloquea los tramos vinculados en orden fijo y revalida antes de guardar. Django Admin mantiene el vuelo en solo lectura para evitar una segunda vía que omita las reglas.
* Enlaces para saltar al contenido, etiquetas de formulario, errores asociados con `aria-describedby`, foco visible, menú con estado accesible, tablas con encabezados y diseño adaptable. La tabla financiera puede desplazarse horizontalmente en pantallas estrechas.

## Ejecución en Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DEBUG = "1"
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py runserver
```

Si `pip` no está disponible en el entorno, usar `uv pip install --python .venv\Scripts\python.exe -r requirements.txt`. En producción configurar `SECRET_KEY`, `DATABASE_URL`, `DEBUG=0` y el resto de variables descritas en README. Las migraciones se ejecutan antes de desplegar; Vercel no las aplica automáticamente.

## Migraciones

* `finanzas/0001_initial`: tarjetas, historial, referencias únicas y restricciones de integridad.
* `vuelos/0003_*`: dos contadores inicializados en cero y restricciones de capacidad/inventario/duración. No elimina campos ni vuelos existentes. Una prueba migra un vuelo de la iteración 1 y comprueba su preservación.

## Validación

Pruebas de regresión de usuarios, reglas horarias y programación de la iteración 1, más pruebas de aislamiento, roles, formularios, dinero, CSRF, idempotencia, rollback, edición, filtros, disponibilidad, paginación y migración con datos previos.

Comprobaciones reproducibles:

```powershell
$env:DEBUG = "1"
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py check
git diff --check
```

La base de datos y las credenciales de producción, el despliegue y las pruebas de carga en PostgreSQL quedan fuera de esta verificación local. Los datos de demostración utilizados para la revisión visual se crean en una base SQLite separada, excluida de Git.
