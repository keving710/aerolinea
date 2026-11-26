# Sistema de compra y reserva de tiquetes aéreos — Iteraciones 1, 2 y 3

Python 3.13 · Django 5.2 · PostgreSQL (Neon/Supabase) · Vercel · Cloudinary (fotos).

## Qué incluye la iteración 1

| HU | Historia | Dónde |
|----|----------|-------|
| 1 | Registro de cliente | `/registro/` |
| 2 | Inicio y cierre de sesión | `/ingresar/`, `/salir/` (POST) |
| 3 | Control de acceso por tipo de usuario | `usuarios/permisos.py` (`rol_requerido`), página 403 |
| 4 | Usuario root por defecto | migración `usuarios/0002_root_por_defecto.py`, `/root/credenciales/` |
| 5 | Creación de administradores | `/root/administradores/`, `/root/administradores/nuevo/` |
| 6 | Completar perfil del administrador | `/perfil/` (aviso en todas las páginas hasta completarlo) |
| 7 | Editar perfil de usuario | `/perfil/` |
| 10 | Código consecutivo de vuelo | `vuelos/models.py` (`Consecutivo`, `VU-00001`) |
| 11 | Vuelos nacionales | `/vuelos/nacional/nuevo/` |
| 12 | Vuelos internacionales (+ regreso) | `/vuelos/internacional/nuevo/`, `/vuelos/<codigo>/regreso/` |
| 13 | Hora de llegada internacional | `vuelos/reglas.py` (zonas horarias con `zoneinfo`) |
| 14 | Validación antes de publicar | `vuelos/forms.py` (solo se publica si todo es válido) |

Los datos de usuario siguen el diagrama entidad-relación (DNI, nombres, apellidos, fecha y lugar de nacimiento, dirección de facturación, género, correo, usuario, contraseña, rol).

La iteración 2 incorpora finanzas simuladas, búsqueda pública, publicación y edición de vuelos. La iteración 3 añade compra y reserva, cancelaciones, promociones y vuelos realizados. Quedan para la iteración 4: noticias, mensajería, check-in, recomendación y chatbot.

## Ejecutar en local

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
export DEBUG=1                                       # Windows (PowerShell): $env:DEBUG="1"
python manage.py migrate        # crea la BD SQLite, el usuario root y las ciudades
python manage.py runserver
python manage.py cargar_vuelos_demo   # opcional: vuelos simulados (ver abajo)
python manage.py test           # 246 pruebas
```

### Vuelos simulados

`python manage.py cargar_vuelos_demo` crea 40 vuelos nacionales y 12 internacionales (cada uno con su
regreso) en los próximos 30 días, con rutas, duraciones y precios realistas. La mitad no tiene
tiquetes vendidos (se pueden editar) y el resto tiene ocupación variada. Opciones:

```bash
python manage.py cargar_vuelos_demo --dias 60 --nacionales 80 --internacionales 20
python manage.py cargar_vuelos_demo --limpiar    # borra antes los vuelos futuros sin ventas y vuelve a cargar
python manage.py cargar_vuelos_demo --semilla 1  # mismos vuelos cada vez
```

Root por defecto: usuario `root`, contraseña `Root2026!` (cámbiala en `/root/credenciales/`).
Se puede definir otra con las variables `ROOT_USERNAME` y `ROOT_PASSWORD` antes del primer `migrate`.

## Despliegue en Vercel

1. Crea una base PostgreSQL en Neon o Supabase y copia la cadena de conexión.
2. **Migra desde tu computador** (Vercel no ejecuta comandos de Django):
   ```bash
   export DATABASE_URL="postgresql://...conexión directa..."
   python manage.py migrate
   ```
3. Crea una cuenta en Cloudinary y copia el `CLOUDINARY_URL` (para las fotos de perfil).
4. En Vercel: *Import Project* → este repositorio, y define las variables de entorno:
   `SECRET_KEY`, `DEBUG=0`, `DATABASE_URL` (cadena *pooled*), `CLOUDINARY_URL`.
5. Despliega. `vercel.json` redirige todas las rutas a `api/index.py`.

Variables de ejemplo en `.env.example`.

## Diseño visual

Bootstrap 5 y Bootstrap Icons vienen incluidos en `static/vendor/` (no dependen de internet). Los colores y estilos propios están en `static/css/app.css` (variables `--marca` y `--acento` al inicio) y la estructura común en `templates/base.html`.

## Decisiones de diseño

- **Roles**: `root`, `administrador`, `cliente`; el visitante es el usuario sin sesión.
- **Horas**: se guardan en UTC y se muestran en la hora local de cada ciudad (Bogotá, Madrid, Londres, New York, Buenos Aires, Miami), con horario de verano automático.
- **Vuelos inválidos**: no se guardan; el administrador ve la lista de errores. El campo `estado` usa los valores del diagrama de clases (programado, cancelado, realizado); hoy solo se usa «programado».
- **Capacidad**: 150 asientos (nacional) y 250 (internacional).


## Iteración 2

Implementa HU **9, 15, 19, 24, 25 y 34–39**, conservando las funciones de usuarios y programación de vuelos de la iteración 1.

* **Inicio y búsqueda:** `/` y `/vuelos/buscar/`. Vuelos con imagen local, información completa y cupos; filtros combinables por código, ruta, fecha/hora local del origen, tipo, duración y precio. Solo vuelos futuros, programados y con disponibilidad.
* **Edición de vuelos:** desde el detalle administrativo, solo administrador y sin tiquetes vendidos ni salida iniciada/realizada. Conserva código, tipo y capacidad y valida los tramos vinculados.
* **Mi billetera:** `/billetera/`, exclusiva del cliente. Tarjetas débito/crédito ficticias, saldo por tarjeta y total, recargas e historial paginado. Los números se enmascaran y no se almacenan completos.
* **Selección de tarjeta y fondos:** `/billetera/simular-pago/` permite verificar el débito simulado sobre la tarjeta elegida y el rechazo por saldo insuficiente. No compra ni reserva tiquetes. Contratos internos de cobro y reembolso preparados para la iteración 3.

Aplicar `python manage.py migrate` antes de iniciar una instalación existente. En Windows puede usarse `.\.venv\Scripts\python.exe` y `$env:DEBUG = "1"`.

Ver [criterios, arquitectura, seguridad, contratos y validación de la iteración 2](docs/ITERACION_2.md).

## Iteración 3

Implementa HU **16, 17, 18 y 26–33**: compra y reserva de tiquetes, cancelaciones, promociones y vuelos realizados.

| HU | Historia | Dónde |
|----|----------|-------|
| 26 | Inicio de compra o reserva desde los resultados | Botones **Comprar** / **Reservar** en `/vuelos/buscar/`, portada y detalle; el visitante es enviado a registrarse |
| 27 | Datos de los viajeros | `/reservas/vuelo/<código>/comprar/` o `/reservar/` (todos los campos obligatorios; un menor no viaja solo) |
| 28 | Reserva de tiquetes | Retiene cupos 24 h; máx. 5 por vuelo; sin viajeros duplicados; root y administrador no pueden |
| 29 | Compra con carrito | `/reservas/carrito/`: elige la tarjeta, valida saldo, solo ida o ida y vuelta |
| 30 | Clase y silla | Primera clase (nacional 1–25, internacional 1–50) o económica; silla aleatoria y libre |
| 31 | Código de reserva y correo | `RES-XXXXXXXX` único, enviado a cada viajero |
| 32 | Cancelación de compra o reserva | `/reservas/<código>/`: compra hasta 1 h antes del vuelo (con reintegro); reserva dentro de sus 24 h |
| 33 | Histórico | `/reservas/`: compras y reservas con su estado y el estado del check-in |
| 16 | Promociones | `/vuelos/<código>/promocion/`: descuento solo sobre los cupos disponibles |
| 17 | Cancelación de vuelos | `/vuelos/<código>/cancelar/`: reubica o reintegra a cada pasajero |
| 18 | Vuelos realizados | `/vuelos/realizados/` (también `/vuelos/cancelados/`) |

Aplica `python manage.py migrate` en instalaciones existentes (nueva app `reservas` y dos campos en `vuelos`).
`python manage.py mantener_reservas` marca como realizados los vuelos que ya salieron y libera las reservas vencidas; esto también ocurre solo, como máximo cada 30 s, al navegar el sitio y en cada compra o reserva.

Los correos se imprimen en la consola si no defines `EMAIL_HOST` (ver `.env.example`).

Ver [decisiones, reglas y verificación de la iteración 3](docs/ITERACION_3.md).
