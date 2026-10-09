# Despliegue de Turnio en Railway

Adaptado de `DEPLOY.md` de jemPOS. Un proyecto de Railway con dos entornos:

| Entorno | Rama | Para qué |
|---|---|---|
| `staging` | `test` | Probar en el celular cada tarea fusionada |
| `production` | `main` | Los negocios reales. Solo se fusiona a `main` con la confirmación de jempo |

Cada entorno tiene sus propios tres servicios: **web** (este repo), **MySQL** y **Redis**. Nada se comparte entre entornos.

---

## 0. Lo que ya está listo en el repo

- `Procfile`: arranca gunicorn (4 workers x 4 hilos, logs a stdout).
- `railway.json`:
  - Antes de cada despliegue corre `python scripts/migrar.py`: aplica las migraciones pendientes. Si una falla, el despliegue se cancela y sigue corriendo la versión anterior.
  - Healthcheck en `/health`, que responde 200 solo si la app llega a MySQL. Está exento del redireccionamiento a HTTPS, porque el chequeo de Railway entra por http interno (a jemPOS esto le marcaba el despliegue como caído).
- `.python-version`: Python 3.13.
- `requirements.txt` incluye `cryptography`, que el conector necesita para autenticarse contra el MySQL 8 de Railway sin TLS en la red interna.
- Las migraciones se prueban contra MariaDB (CI) y contra MySQL 8.0.

---

## 1. Crear el proyecto (una vez)

1. railway.com → **New Project** → **Deploy from GitHub repo** → `jempo2002/turnio`. Railway crea el entorno `production`.
2. En el servicio web: **Settings → Source → Branch** = `main`.
3. **+ New → Database → Add MySQL** y **+ New → Database → Add Redis**. Deja sus nombres como `MySQL` y `Redis` (las variables del paso 2 los usan).
4. El primer despliegue falla porque faltan las variables. Es normal.

## 2. Variables del servicio web

Ninguna contraseña va en el repositorio. Cada dato vive en el servicio que lo
guarda, y el servicio web solo lo referencia:

| Dónde vive | Qué guarda | Quién lo define |
|---|---|---|
| **Repositorio** (git) | Código, `requirements.txt`, `Procfile`, `railway.json`, `.env.example` (plantilla sin valores) | Se sube con `git push` |
| **MySQL** (servicio de Railway) | Usuario, contraseña, host y base. Y los datos del negocio | Railway lo crea solo |
| **Redis** (servicio de Railway) | Sesiones de usuario y contadores de intentos de login. No guarda datos de negocio | Railway lo crea solo |
| **Servicio web** → Variables | Las variables de la tabla de abajo | Tú, en el panel |

Servicio web → **Variables** → **Raw Editor**, y pega:

```
SECRET_KEY=<genera una, ver abajo>
FLASK_ENV=production
DB_HOST=${{MySQL.MYSQLHOST}}
DB_PORT=${{MySQL.MYSQLPORT}}
DB_USER=${{MySQL.MYSQLUSER}}
DB_PASSWORD=${{MySQL.MYSQLPASSWORD}}
DB_NAME=${{MySQL.MYSQLDATABASE}}
REDIS_URL=${{Redis.REDIS_URL}}
APP_UTC_OFFSET=-5
LOG_DIR=logs
```

| Variable | Obligatoria | Valor | Qué hace |
|---|---|---|---|
| `SECRET_KEY` | Sí | Generada (ver abajo) | Firma las cookies de sesión |
| `FLASK_ENV` | Sí | `production` | Fuerza HTTPS, HSTS y cookie `Secure`. Con `development` se apaga |
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Sí | Referencias a MySQL | Conexión a la base. Si el valor es una IP, está mal |
| `REDIS_URL` | Sí en producción | Referencia a Redis | Sesiones y límites de intentos compartidos entre workers. Sin ella la app no arranca en producción |
| `APP_UTC_OFFSET` | No (por defecto `-5`) | `-5` | Hora del negocio: Colombia |
| `LOG_DIR` | No (por defecto `logs`) | `logs` | Carpeta de logs de correo |
| `EMAIL_SENDER`, `EMAIL_PASSWORD` | No | Correo y contraseña de aplicación de Google | Recuperar contraseña e invitaciones por correo. Sin ellas el enlace de invitación igual sale por WhatsApp |
| `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT` | No (por defecto Gmail) | `smtp.gmail.com`, `587` | Servidor de correo |
| `SESSION_HORAS` | No (por defecto `12`) | Horas sin actividad | Cuánto dura una sesión inactiva |
| `WEB_CONCURRENCY`, `GUNICORN_THREADS`, `DB_POOL_SIZE` | No | Ver `Procfile` | Solo si se necesita más capacidad. Por defecto 4 workers x 4 hilos |

- `SECRET_KEY`: `python -c "import secrets; print(secrets.token_hex(32))"`. Una distinta por entorno, y nunca la de tu `.env` local.
- Las `${{...}}` van tal cual, con las llaves: Railway las cambia por el host interno. Si el log dice `Can't connect to MySQL server on '127.0.0.1'`, se copiaron valores locales en vez de las referencias.
- Si tu servicio de base o de Redis tiene otro nombre distinto de `MySQL` o `Redis`, cámbialo en las referencias.

Al guardar, Railway redespliega: migra la base de cero y arranca. En **Deployments → Logs** debe verse `N migraciones aplicadas.` y el arranque de gunicorn.

## 3. Entorno de pruebas (`staging`)

1. Arriba, el selector de entorno → **New Environment** → `staging` → **Duplicate environment** de `production`. Copia los tres servicios con sus variables y con bases nuevas y vacías.
2. En `staging`, servicio web → **Settings → Source → Branch** = `test`.
3. Cambia su `SECRET_KEY` por una nueva.
4. Opcional, para tener datos de prueba: ver *Cuentas demo* en el paso 4.

## 4. Primer usuario Master (en cada entorno)

Con la [CLI de Railway](https://docs.railway.com/guides/cli) instalada y `railway link` hecho en la carpeta del repo:

```bash
railway ssh --environment production --service <servicio web>
python scripts/crear_master.py "Tu nombre" tu@correo.com   # pide la contraseña
```

### Cuentas demo (solo staging)

Para probar con datos de ejemplo, en `staging`:

```bash
railway ssh --environment staging --service <servicio web>
python scripts/crear_demo.py      # pide la contraseña de las cuentas demo
```

Crea dos negocios con citas de hoy, servicios y productos. Todas las cuentas usan la misma contraseña:

| Negocio | Correo | Rol |
|---|---|---|
| Barbería Turnio Demo (prueba del Pro) | `admin@turnio.demo` | Admin |
| | `admin2@turnio.demo` | Admin (el segundo, tope del plan) |
| | `recepcion@turnio.demo` | Recepción |
| | `carlos@turnio.demo`, `junior@turnio.demo` | Profesional |
| Salón Turnio Multisede Demo (Multisede, 3 sedes) | `multisede@turnio.demo` | Admin de todas las sedes |
| | `norte@turnio.demo` | Recepción, sede Norte |
| | `laura@turnio.demo`, `sofia@turnio.demo`, `valeria@turnio.demo` | Profesional (Centro, Norte, Sur) |

La tercera sede del salón pasa las 2 incluidas: nace con el montaje pendiente y suma la sede extra a la mensualidad en `/panel-master`.

Se puede correr las veces que sea: lo que ya existe no se toca y solo se crean las cuentas que falten. Como la contraseña es conocida, se niega a correr en el entorno `production` de Railway (o con `FLASK_ENV=production` fuera de Railway) salvo con `--en-produccion`.

El Master entra en `/login` y desde `/panel-master` administra los negocios. Los negocios también se registran solos en `/registro`.

## 5. Dominio

Servicio web → **Settings → Networking**:

- Mientras tanto: **Generate Domain** da una URL `*.up.railway.app` con HTTPS.
- Dominio propio: **Custom Domain**. Railway muestra un `CNAME` y un `TXT` que se copian tal cual en el DNS del dominio. Es lo mismo que se hizo con jemPOS (ver su `DEPLOY.md`, sección 6). Sugerencia: el dominio principal para `production` y `staging.<dominio>` para pruebas.

## 6. Respaldos

Railway no respalda MySQL por defecto. En `production`, servicio MySQL → **Backups**: activa los respaldos programados (diarios). Antes de cada fusión a `main` que traiga migraciones nuevas, saca además uno manual desde la misma pestaña.

## 7. Comprobación

- `https://<dominio>/health` → `{"ok": true, "app": "Turnio"}`.
- `/registro` crea un negocio y entra al panel.
- En el celular: agenda, cobro de una cita, venta rápida y cierre de caja.

## Límites conocidos

- **Una base por entorno, sin réplicas.** Para más tráfico basta con subir `WEB_CONCURRENCY` y `GUNICORN_THREADS`. Las conexiones a MySQL son workers x (hilos + 2).
- **Las migraciones se aplican antes del código nuevo.** Una migración que borre o renombre algo que la versión anterior todavía usa rompe esa versión durante el despliegue. Por eso las migraciones de Turnio solo agregan cosas. Si alguna vez hay que borrar, se hace en dos despliegues.
