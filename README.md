# Sistema de compra y reserva de tiquetes aéreos — Iteración 1

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

Quedan para siguientes iteraciones: HU 8 (noticias), HU 9 (finanzas), búsqueda, compra, reserva, check-in y chatbot.

## Ejecutar en local

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
export DEBUG=1                                       # Windows (PowerShell): $env:DEBUG="1"
python manage.py migrate        # crea la BD SQLite y el usuario root
python manage.py runserver
python manage.py test           # 54 pruebas
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
