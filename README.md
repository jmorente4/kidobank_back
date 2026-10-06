# Kidobank Backend

API para una aplicacion de educacion financiera familiar. Permite que adultos y
menores gestionen **Kidos**, una moneda simulada, con cuentas, pagas, ahorro,
bonos, indices tematicos, tareas remuneradas y un mercadillo.

No conecta con entidades bancarias ni ejecuta inversiones o pagos con dinero real.
Este repositorio contiene el backend; la interfaz, la captura de camara y el
escaneo de QR corresponden al frontend.

## Indice

- [Tecnologias y arquitectura](#tecnologias-y-arquitectura)
- [Instalacion y ejecucion](#instalacion-y-ejecucion)
- [Despliegue en Raspberry Pi con Docker](#despliegue-en-raspberry-pi-con-docker)
- [Configuracion](#configuracion)
- [Autenticacion y permisos](#autenticacion-y-permisos)
- [Catalogo de endpoints](#catalogo-de-endpoints)
- [Flujos funcionales](#flujos-funcionales)
- [Economia automatica](#economia-automatica)
- [Modelos y estados](#modelos-y-estados)
- [Integracion con el frontend](#integracion-con-el-frontend)
- [Pruebas](#pruebas)
- [Alcance actual y consideraciones operativas](#alcance-actual-y-consideraciones-operativas)

## Tecnologias y arquitectura

- Python: el entorno de desarrollo actual utiliza 3.10.
- FastAPI y Uvicorn: API HTTP y servidor ASGI.
- SQLAlchemy 2: modelos, consultas y transacciones.
- PostgreSQL y psycopg2: base de datos de la aplicacion.
- Pydantic 2 y pydantic-settings: contratos y configuracion.
- JWT y Passlib: autenticacion y hashes de contrasenas/PIN.
- Pillow y python-multipart: subida y optimizacion de fotos.
- Pytest, SQLite en memoria y TestClient: pruebas.

```text
app/
  main.py                  Aplicacion, CORS, inicio y tareas periodicas
  api/deps.py              Autenticacion, roles y acceso familiar
  api/v1/router.py         Registro de rutas publicadas
  api/v1/endpoints/        Operaciones HTTP por funcionalidad
  core/                   Configuracion y seguridad
  db/                     Sesiones, registro de modelos y compatibilidad
  models/                 Entidades SQLAlchemy
  schemas/                Entradas y respuestas Pydantic
  services/               Economia, patrimonio, fotos y control de intentos
  crud/                   Modulos de acceso a datos
tests/                    Pruebas de comportamiento
seed_db.py                Datos iniciales opcionales de desarrollo
requirements.txt          Dependencias de ejecucion
```

Los endpoints utilizan sesiones de base de datos por peticion. Operaciones como
las transferencias, aprobaciones de tareas y verificaciones de PIN utilizan
bloqueos de fila en PostgreSQL para coordinar cambios concurrentes.

## Instalacion y ejecucion

Ejemplo para Windows/PowerShell, desde la raiz del repositorio:

```powershell
py -3.10 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Editar .env con la conexion a PostgreSQL y una SECRET_KEY propia.
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Crear previamente la base de datos PostgreSQL y un usuario con permisos para
crear tablas y aplicar las actualizaciones de compatibilidad.

Al iniciar el servidor:

1. Se crean las tablas que falten.
2. Se aplican actualizaciones aditivas para instalaciones anteriores.
3. Se inicia la comprobacion periodica de economia.

Direcciones locales:

| Recurso | URL |
|---|---|
| Estado del servicio | `http://localhost:8000/health` |
| API | `http://localhost:8000/api/v1` |
| Swagger UI | `http://localhost:8000/docs` |
| ReDoc | `http://localhost:8000/redoc` |
| Contrato OpenAPI | `http://localhost:8000/openapi.json` |

### Datos de ejemplo

Opcional, **solo para desarrollo**:

```powershell
.\venv\Scripts\python.exe seed_db.py
```

El script crea un adulto y una cuenta con saldo de ejemplo si no existe ningun
adulto. Contiene credenciales conocidas de demostracion: no utilizarlo en
produccion. Para una instalacion normal, registrar al adulto mediante la API.
El script crea tablas, pero no ejecuta todas las actualizaciones de compatibilidad;
en una base de datos antigua, iniciar primero la aplicacion.

## Despliegue en Raspberry Pi con Docker

Preparado para Raspberry Pi OS/Linux **64 bits (`aarch64`)**, con Docker Engine
y Docker Compose v2. El frontend existente puede continuar en el puerto `8081`.
La API se publica en `8000`; PostgreSQL solo es accesible en la red de Compose,
sin publicar `5432` en la Raspberry Pi.

Archivos:

- [Dockerfile](Dockerfile): Python 3.11, usuario sin privilegios y un worker.
- [compose.yaml](compose.yaml): API, PostgreSQL 16, salud y volumen persistente.
- [.dockerignore](.dockerignore): solo envia codigo de aplicacion y dependencias
  al build; excluye secretos, entornos locales, fotos de prueba y archivos Git.
- [.env.raspberry.example](.env.raspberry.example): plantilla de despliegue.

Los comandos de esta seccion se ejecutan en la **terminal Linux de la Raspberry
Pi**, no en PowerShell.

### 1. Preparar el servidor

```sh
uname -m
docker version
docker compose version
git clone https://github.com/jmorente4/kidobank_back.git
cd kidobank_back
cp .env.raspberry.example .env.raspberry
chmod 600 .env.raspberry
```

Si el repositorio es privado, utilizar el metodo de autenticacion Git habitual.
Si ya esta clonado, actualizar esa copia en lugar de crear otra. No copiar el
`venv` de Windows al servidor.

Crear dos secretos diferentes:

```sh
openssl rand -hex 32
openssl rand -hex 32
nano .env.raspberry
```

Asignar uno a `POSTGRES_PASSWORD` y otro a `SECRET_KEY`. No publicar esos valores.
La plantilla deja ambos vacios a proposito: Compose rechazara el arranque hasta
que se rellenen. Utilizar hex evita problemas de codificacion de la contrasena
en la URL PostgreSQL construida por la configuracion actual.

Cambiar las IP de ejemplo por la IP real de la Raspberry Pi, por ejemplo:

```dotenv
CORS_ORIGINS=["http://192.168.1.50:8081"]
PASSWORD_RESET_URL=http://192.168.1.50:8081/reset-password
```

El origen CORS debe coincidir exactamente con lo que abre el navegador. Si se
utiliza tambien un nombre local, incluir ambos origenes en la lista JSON.
Puede configurarse `API_BIND_IP` con la IP LAN para limitar donde escucha;
el valor por defecto `0.0.0.0` escucha en todas las interfaces del servidor.
No reenviar el puerto de la API desde el router a Internet.

### 2. Construir y arrancar

```sh
docker compose --env-file .env.raspberry config --quiet
docker compose --env-file .env.raspberry up -d --build
docker compose --env-file .env.raspberry ps
docker compose --env-file .env.raspberry logs --tail=100 api
curl --fail http://127.0.0.1:8000/health
```

Usar `--env-file .env.raspberry` en **todos** los comandos: configura tanto la
interpolacion de Compose como el entorno de la API. Si `API_BIND_IP` se ha fijado
a la IP LAN, utilizar esa IP en el comando curl en lugar de `127.0.0.1`.
La primera construccion puede tardar, especialmente en una Raspberry Pi.

La API espera a que PostgreSQL este preparado; crea tablas y aplica compatibilidad
antes de aceptar peticiones. El healthcheck de la API verifica HTTP y una consulta
a PostgreSQL. Un contenedor unhealthy requiere investigar los logs: la politica
de reinicio reinicia procesos que terminan, no contenedores solo unhealthy.

Desde otro equipo de la red:

- API: `http://IP_DE_LA_RASPBERRY:8000/api/v1`
- Swagger: `http://IP_DE_LA_RASPBERRY:8000/docs`
- Frontend existente: `http://IP_DE_LA_RASPBERRY:8081`

Comprobar que el cortafuegos permite los puertos necesarios **solo desde la LAN**.

### 3. Conectar el frontend existente

Configurar su URL base de API con la IP accesible desde el navegador:
`http://IP_DE_LA_RASPBERRY:8000/api/v1` si el cliente agrega rutas como `/users/`,
o `http://IP_DE_LA_RASPBERRY:8000` si ya agrega `/api/v1`.
No duplicar ese prefijo.

**No utilizar `http://api:8000` ni `http://localhost:8000` en el navegador**:
`api` es un nombre de la red Docker y localhost es el equipo/telefono que abre la
web, no la Raspberry Pi. No es necesario compartir la red Docker del frontend
para esta conexion directa desde el navegador.

El nombre de la variable depende del repositorio frontend. Si es una variable
Vite integrada en el bundle, cambiar el entorno del build y **reconstruir el
contenedor frontend**; cambiar solo su entorno de ejecucion no modifica el
JavaScript ya generado. Verificar en la pestaña Network que las peticiones
apuntan a la IP y puerto correctos.

Registrar el adulto desde el frontend o Swagger y crear sus hijos. El contenedor
no ejecuta el seed ni incorpora cuentas con contrasenas de demostracion.

Este despliegue crea una base de datos nueva. Para conservar usuarios y datos
del entorno de desarrollo, realizar una exportacion/restauracion planificada;
no copiar archivos de PostgreSQL en funcionamiento al volumen.

### 4. HTTP local, camara y fotos

HTTP por IP es util para pruebas en una LAN de confianza, pero no cifra PIN,
contrasena, tokens ni fotos. No es un despliegue con HTTPS.
La captura de webcam mediante `getUserMedia` normalmente necesita HTTPS; localhost
es una excepcion, pero una IP LAN no. El selector de archivos/foto del movil puede
funcionar segun navegador, pero no sustituye ese requisito para webcam.

Para usar camara web de forma fiable y proteger credenciales, el siguiente paso
es un proxy HTTPS y un certificado confiable en los dispositivos. No se incluye
un certificado autofirmado ni se desactiva la seguridad del navegador.

### 5. Datos, copias de seguridad y actualizaciones

Los datos, fotos, historicos y cursores estan en el volumen `postgres_data` de
Compose. Sobreviven a reconstrucciones y a `docker compose down`.
**No ejecutar `down -v`** salvo que se quiera borrar expresamente toda la base.
Si cambia el nombre del proyecto Compose, se seleccionara otro volumen.

Copia logica, sin exponer PostgreSQL al host:

```sh
umask 077
docker compose --env-file .env.raspberry exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > kidobank.dump
test -s kidobank.dump
docker compose --env-file .env.raspberry exec -T db \
  pg_restore --list < kidobank.dump
```

Comprobar el codigo de salida de los comandos, guardar la copia fuera de la
Raspberry Pi y probar periodicamente la restauracion en una base separada.
La copia contiene datos personales y fotos; protegerla igual que la base.
Respaldar tambien `.env.raspberry` de forma privada para conservar los secretos,
sin guardarlo en Git ni en el build de Docker.

Para restaurar en una **base de destino vacia**, con la API detenida y despues
de verificar el destino:

```sh
docker compose --env-file .env.raspberry stop api
docker compose --env-file .env.raspberry exec -T db \
  sh -c 'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < kidobank.dump
docker compose --env-file .env.raspberry start api
```

No restaurar sobre tablas existentes sin un procedimiento explicito. Si falla,
investigar antes de volver a iniciar la API.

Actualizar codigo tras hacer copia de seguridad:

```sh
git pull --ff-only
docker compose --env-file .env.raspberry up -d --build
docker compose --env-file .env.raspberry ps
docker compose --env-file .env.raspberry logs --tail=100 api
curl --fail http://127.0.0.1:8000/health
```

Mantener un solo worker de API: el scheduler se inicia por proceso. PostgreSQL
esta fijado a la version mayor 16; no cambiar de version mayor usando directamente
el mismo volumen. Cambiar `POSTGRES_PASSWORD` en el archivo no cambia la
contrasena de un usuario ya creado: requiere una rotacion coordinada en la base.
Cambiar `SECRET_KEY` invalida los JWT existentes.

La API corre sin privilegios, con filesystem de solo lectura y un `/tmp` temporal
para multipart. Los logs se consultan con Docker; no se escriben fotos en el
filesystem. `bcrypt==3.2.2` conserva la compatibilidad con el Passlib actual.
Los requisitos restantes siguen el manifiesto existente; para despliegues
totalmente reproducibles se necesita fijar tambien el resto de dependencias y
los digests de imagen tras validar el build en ARM64.

## Configuracion

Se lee el archivo `.env` mediante [Settings](app/core/config.py). No subir
credenciales reales ni el archivo `.env` al repositorio.

| Variable | Requerida / valor por defecto | Funcion |
|---|---|---|
| `POSTGRES_SERVER` | Requerida | Servidor PostgreSQL |
| `POSTGRES_PORT` | `5432` | Puerto |
| `POSTGRES_USER` | Requerida | Usuario |
| `POSTGRES_PASSWORD` | Requerida | Contrasena |
| `POSTGRES_DB` | Requerida | Base de datos |
| `DATABASE_URL` | Opcional | Sustituye la URL construida con los campos anteriores |
| `SECRET_KEY` | Requerida | Clave privada de firma JWT |
| `ALGORITHM` | `HS256` | Algoritmo JWT |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Duracion del token: 24 horas |
| `CORS_ORIGINS` | localhost en puertos 5173 y 3000 | Origenes permitidos, lista JSON |
| `PROJECT_NAME` | `Kidobank API` | Nombre configurable |
| `ENVIRONMENT` | `local` | Etiqueta de entorno |
| `SMTP_HOST` | Opcional | Servidor de correo |
| `SMTP_PORT` | `587` | Puerto SMTP |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Opcionales | Credenciales SMTP |
| `SMTP_FROM_EMAIL` | Opcional | Remitente |
| `SMTP_USE_TLS` | `True` | TLS SMTP |
| `PASSWORD_RESET_URL` | `http://localhost:5173/reset-password` | Pantalla frontend de recuperacion |

Los campos `POSTGRES_*` obligatorios siguen siendo necesarios en Settings aunque
se suministre `DATABASE_URL`. Si la contrasena contiene caracteres especiales,
utilizar una URL de conexion correctamente codificada.
La URL generada utiliza `postgresql+psycopg2://` para seleccionar explicitamente
el driver instalado (`psycopg2-binary`). Si se define `DATABASE_URL` manualmente,
utilizar tambien ese prefijo; `postgresql://` puede seleccionar otro driver
segun la version de SQLAlchemy y provocar `No module named 'psycopg'`.

Ejemplo de CORS:

```dotenv
CORS_ORIGINS=["http://localhost:5173","https://frontend.example.com"]
```

## Autenticacion y permisos

### Roles

- **PADRE / MADRE**: administradores con los mismos permisos sobre su familia.
- **NINO / FAMILIAR**: miembros con los mismos permisos limitados sobre sus datos.
  FAMILIAR permite incluir abuelos, tios o primos; acceden con PIN y QR, no con
  contrasena de administrador.

`familia_id` identifica la familia compartida usando el ID de su primer
administrador. `padre_id` conserva el administrador que creo al miembro por
compatibilidad; no limita el acceso del otro administrador.
Un registro publico PADRE o MADRE crea una familia independiente. Para compartir
familia, un administrador autenticado crea al otro mediante `POST /users/`,
indicando su rol y contrasena. No se fusionan familias por nombre o email.
El rol y la familia no se pueden cambiar mediante el PATCH de perfil.

El adulto no tiene acceso general a los datos privados de otras familias.
Un menor normalmente solo accede a sus propios datos. Excepciones de catalogo:
los productos de inversion, noticias y articulos del mercadillo son globales
para usuarios autenticados, no estan particionados por familia.

### Token

El login devuelve `access_token`, `token_type` y un resumen de `user`. Enviar:

```http
Authorization: Bearer <access_token>
```

El adulto entra con email y contrasena. El acceso por PIN utiliza `nombre_usuario`,
`user_id` o `qr_uuid` y un PIN de exactamente cuatro digitos. El apodo esta
disponible para NINO/FAMILIAR y se envia sin los otros identificadores (mezclarlos
devuelve 400). Se conserva la prioridad del QR en clientes antiguos que envian
ID y QR juntos. Un QR o apodo identifica al usuario: **no sustituye al PIN**.

### Limite de PIN y desbloqueo

- Login por apodo, ID, QR y comprobacion del PIN actual comparten contador.
- Tras **3 fallos**, NINO/FAMILIAR queda bloqueado sin caducidad.
- Durante el bloqueo se rechaza el acceso, incluido el uso de un token existente.
- Cualquier PADRE/MADRE de su familia puede ejecutar `POST /users/{user_id}/unlock`.
- El desbloqueo reinicia los intentos y no cambia el PIN.
- Cambiar el PIN de un menor bloqueado no lo desbloquea.
- El estado `bloqueado_por_pin` aparece en las respuestas de usuario.
- Las cuentas de adulto conservan el bloqueo temporal de 15 minutos.
- Un login correcto reinicia los fallos si la cuenta no esta bloqueada.

## Catalogo de endpoints

Todas las rutas siguientes llevan el prefijo **`/api/v1`**, salvo `/health`.
Los cuerpos son JSON excepto la subida de foto. Las listas se devuelven como
arrays, no como objetos paginados. Swagger/OpenAPI contiene el contrato detallado
de campos, limites, respuestas y errores.

Permisos utilizados en las tablas:

- **Publico**: no requiere token.
- **Autenticado**: cualquier rol con token valido y no bloqueado.
- **Propio/familia**: NINO/FAMILIAR sobre si mismo; PADRE/MADRE sobre su familia.
- **Padre** (incluido "Padre del hijo"): PADRE o MADRE de la familia del miembro.
- **Hijo asignado**: exclusivamente el destinatario NINO o FAMILIAR.

### Salud y autenticacion

| Metodo | Ruta | Permiso | Entrada / resultado |
|---|---|---|---|
| GET | `/health` | Publico | Estado y nombre de la API |
| POST | `/auth/login/parent` | Publico | `email`, `password`; devuelve token y usuario |
| POST | `/auth/login/pin` | Publico | `pin` y `nombre_usuario`, `user_id` o `qr_uuid`; devuelve token y usuario |
| POST | `/auth/password/forgot` | Publico | `email`; respuesta generica 202, envio por SMTP |
| POST | `/auth/password/reset` | Publico | `token`, `new_password`; 204 al restablecer |

La recuperacion requiere `SMTP_HOST` y `SMTP_FROM_EMAIL`; sin configuracion
responde 503. Los tokens de recuperacion duran una hora y son de un solo uso.

### Usuarios, perfiles, fotos y tarjetas

| Metodo | Ruta | Permiso | Entrada / resultado |
|---|---|---|---|
| GET | `/users/` | Autenticado | Familia visible; filtros `rol`, `limit=50`, `offset=0` |
| POST | `/users/` | Publico / Padre | Registro publico PADRE/MADRE; con token crea cualquier rol en la misma familia |
| GET | `/users/me` | Autenticado | Perfil actual |
| GET | `/users/children` | Padre | Solo NINO de la familia; para FAMILIAR usar `/users/?rol=FAMILIAR` |
| POST | `/users/children` | Padre | Crear hijo NINO con PIN |
| GET | `/users/{user_id}` | Propio/familia | Perfil |
| PATCH | `/users/{user_id}` | Propio/familia | `nombre`, `apellidos`, `email`, `avatar_url`; `nombre_usuario` solo por PADRE/MADRE |
| DELETE | `/users/{user_id}` | Padre del hijo | Eliminar hijo; rechaza si tiene saldo positivo en cuentas |
| POST | `/users/{user_id}/avatar` | Propio/familia | Multipart, campo `file`; devuelve perfil |
| GET | `/users/{user_id}/avatar` | Propio/familia | Bytes JPEG de la foto almacenada |
| PATCH | `/users/{user_id}/pin` | Propio/familia | `pin_nuevo`; el propio menor necesita `pin_actual` |
| POST | `/users/{user_id}/unlock` | Padre del hijo | Sin cuerpo; devuelve usuario desbloqueado |
| GET | `/users/{user_id}/cards` | Propio/familia | Tarjetas QR, incluidas inactivas |
| POST | `/users/{user_id}/cards` | Padre del hijo | `{}` o `qr_uuid`; emite tarjeta y revoca anteriores activas |
| PATCH | `/users/{user_id}/cards/{card_id}` | Padre del hijo | `activa`: activar o revocar |

Alta de usuario: `nombre`, `email`, `rol`, y `password` para PADRE/MADRE o `codigo_pin`
para NINO/FAMILIAR. Opcionales: `apellidos`, `avatar_url`, `tarjeta_qr`, `nombre_usuario`.
`/users/children` mantiene el alta exclusiva de NINO; FAMILIAR se crea en `/users/`.
Cada alta crea una cuenta corriente con saldo cero.

`nombre_usuario` es opcional y exclusivo de NINO/FAMILIAR: 3-30 letras ASCII
sin acentos, numeros o guion bajo, sin espacios interiores. Se recortan espacios
exteriores y se guarda en minusculas. Es unico en toda la aplicacion, tambien
entre familias y sin distinguir mayusculas; un duplicado devuelve 409.
El indice unico en la base de datos protege tambien frente a altas simultaneas.
Solo PADRE/MADRE de la familia pueden asignarlo, cambiarlo o borrarlo con `null`
en PATCH. Omitirlo conserva su valor. Aparece en perfiles y en la respuesta de
login; no sustituye al nombre real ni al PIN. Los usuarios existentes conservan
`null` hasta que su administrador les asigne un apodo.

`apellidos` admite hasta 150 caracteres y `avatar_url` hasta 255. En PATCH,
omitirlos conserva su valor; enviar `null` los borra. Borrar o sustituir
`avatar_url` tambien elimina la foto almacenada que corresponda.

### Cuentas

| Metodo | Ruta | Permiso | Entrada / resultado |
|---|---|---|---|
| GET | `/accounts/me` | Autenticado | Cuentas propias |
| GET | `/accounts/user/{user_id}` | Propio/familia | Cuentas del usuario |
| GET | `/accounts/{account_id}` | Propio/familia | Detalle y valoracion |
| POST | `/accounts/` | Padre | `usuario_id`, `nombre`, `tipo`; opcionales `saldo_inicial`, `tasa_interes` |
| PATCH | `/accounts/{account_id}` | Propio/familia | Renombrar con `nombre` |
| DELETE | `/accounts/{account_id}` | Padre | Sin saldo positivo ni bonos asociados; 204 |
| POST | `/accounts/transfer` | Propio/familia | `cuenta_origen_id`, `cuenta_destino_id`, `monto`, `concepto` opcional |

Tipos: `CORRIENTE`, `AHORRO`, `INVERSION`. Los nombres son unicos por usuario
sin distinguir mayusculas/minusculas. Solo AHORRO admite una tasa distinta de
cero. Al crear una cuenta propia del padre, el saldo inicial se fuerza a cero;
el padre puede recargarla con el endpoint de deposito.

Las cuentas INVERSION incluyen `valor_bonos`, `valor_inversiones` y
`patrimonio_total`, calculados con los activos del usuario. Son una vista
patrimonial: no sumar repetidamente estas valoraciones si existen varias cuentas
de inversion del mismo usuario.

### Transacciones, recargas y pagas

| Metodo | Ruta | Permiso | Entrada / resultado |
|---|---|---|---|
| GET | `/transactions/` | Autenticado | Historial familiar visible |
| GET | `/transactions/me` | Autenticado | Historial de cuentas propias |
| GET | `/transactions/account/{account_id}` | Propio/familia | Historial de una cuenta |
| GET | `/transactions/user/{user_id}` | Propio/familia | Historial de un usuario |
| POST | `/transactions/` | Propio/familia | Transferir: origen, destino, `monto`, `concepto` |
| POST | `/transactions/deposito` | Padre | Recargar cuenta propia: `cuenta_destino_id`, `monto`, `concepto` opcional |
| POST | `/transactions/paga` | Padre | Abonar al hijo: destino, `monto`, origen y concepto opcionales |

Las consultas aceptan `limit=50`, `offset=0` y ordenan por fecha descendente.
La transferencia registra siempre tipo `TRANSFERENCIA`, aunque el esquema de
entrada contenga un campo `tipo`. Para transferencias usar preferentemente
`/accounts/transfer`, que tambien impide origen y destino iguales.

La paga con `cuenta_origen_id` descuenta de una cuenta propia del padre; sin
origen emite Kidos directamente. No hay programacion automatica de pagas.

### Bonos de renta fija

| Metodo | Ruta | Permiso | Entrada / resultado |
|---|---|---|---|
| GET | `/bonds/offers` | Autenticado | Padre: ofertas propias; hijo: activas de su padre |
| POST | `/bonds/offers` | Padre | `titulo`, `tasa_interes`, `plazo_dias`, `monto_minimo` opcional |
| DELETE | `/bonds/offers/{offer_id}` | Padre propietario | Retirar oferta; 204 |
| POST | `/bonds/` | NINO/FAMILIAR | `oferta_id`, `cuenta_origen_id`, `monto_invertido` |
| GET | `/bonds/` | Propio/familia | Filtrar con `usuario_id`; sin filtro, usuario actual |
| POST | `/bonds/{bond_id}/redeem` | Propio/familia | Sin cuerpo; rescate a la cuenta de origen |

El interes de la oferta es el rendimiento total al vencimiento, no una tasa
anual: `0.05` representa un 5% del capital. El cobro es explicito, no automatico.

### Metas de ahorro

| Metodo | Ruta | Permiso | Entrada / resultado |
|---|---|---|---|
| GET | `/goals/` | Autenticado | Metas propias o de la familia visible |
| POST | `/goals/` | Propio/familia | `cuenta_id`, `titulo`, `monto_objetivo`; descripcion e icono opcionales |
| POST | `/goals/{goal_id}/deposit` | Propio/familia | `monto` descontado de la cuenta vinculada |
| DELETE | `/goals/{goal_id}` | Propio/familia | Devuelve lo ahorrado a la cuenta vinculada y elimina la meta; 204 |

El borrado registra una transaccion TRANSFERENCIA de devolucion si hay ahorro.
No hay endpoints de retirada parcial o edicion de metas. El frontend debe limitar
la aportacion a lo que falta para el objetivo: actualmente se descuenta todo el
importe solicitado, aunque el progreso se limita a `monto_objetivo`.

### Inversiones, noticias e historico

| Metodo | Ruta | Permiso | Entrada / resultado |
|---|---|---|---|
| GET | `/investments/products` | Autenticado | Productos activos globales |
| POST | `/investments/products` | Padre | Crear activo; campos indicados abajo |
| GET | `/investments/products/{product_id}` | Autenticado | Detalle |
| DELETE | `/investments/products/{product_id}` | Padre | Desactivar, conservando posiciones e historico; 204 |
| GET | `/investments/products/{product_id}/history` | Autenticado | Puntos de precio en orden cronologico |
| POST | `/investments/products/{product_id}/buy` | Propio/familia | `cuenta_id`, `monto_invertido_kidos` |
| GET | `/investments/news` | Autenticado | Noticias activas globales |
| POST | `/investments/news` | Padre | `titulo`, `descripcion`, `impacto_pct`, `producto_id` opcional |
| GET | `/investments/positions/me` | Autenticado | Posiciones del usuario actual |
| POST | `/investments/positions/{investment_id}/sell` | Propio/familia | `cuenta_id` corriente del propietario |

Alta de activo:

```json
{
  "nombre": "Indice Tecnologia",
  "codigo": "TECH-01",
  "tipo": "INDICE",
  "descripcion": "Indice tematico simulado",
  "precio_actual_kidos": 100,
  "tasa_rentabilidad": 0.05,
  "volatilidad": 0.03
}
```

`tipo` admite `INDICE` y `BONO`; `duracion_dias` es opcional.
`tasa_rentabilidad` es anual esperada, entre 0 y 0.2, no garantizada.
`volatilidad` es semanal, entre 0 y 1.

Los productos BONO de este catalogo y las ofertas de `/bonds/offers` son
funcionalidades diferentes: el flujo de renta fija familiar usa `/bonds/`.
Desactivar impide nuevas compras y simulaciones del activo y lo oculta del listado
de activos. El detalle e historico siguen accesibles y las posiciones existentes
pueden venderse al ultimo precio. Como el catalogo es global y no hay creador
asociado, cualquier PADRE/MADRE puede desactivar un producto.

### Economia y patrimonio

| Metodo | Ruta | Permiso | Entrada / resultado |
|---|---|---|---|
| GET | `/economy/inflation` | Autenticado | Politica o **200 con `null`** si no existe |
| POST | `/economy/inflation` | Padre | `tasa_semanal`, `nombre` opcional; crea politica |
| PATCH | `/economy/inflation` | Padre | Modificar politica existente |
| PATCH | `/economy/savings-rate/{account_id}` | Padre, cuenta propia/hijo | `tasa_semanal`, solo AHORRO |
| GET | `/economy/summary/me` | Autenticado | Patrimonio propio |
| GET | `/economy/summary/{user_id}` | Propio/familia | Patrimonio de un usuario |

Las tasas semanales se expresan como decimal: `0.02` = 2%, entre 0 incluido y
1 excluido. Crear otra politica responde 409; modificar una inexistente, 404.
La politica de inflacion es global, no una politica independiente por familia.

El resumen incluye saldos, inversiones de mercado, bonos, metas, fondos en escrow
y patrimonio total. La tasa real semanal es
`(1 + tasa_nominal_semanal) / (1 + inflacion_semanal) - 1`.

### Mercadillo

| Metodo | Ruta | Permiso | Entrada / resultado |
|---|---|---|---|
| GET | `/market/items` | Autenticado | Catalogo global; filtro `estado` opcional |
| GET | `/market/items/{item_id}` | Autenticado | Detalle |
| POST | `/market/items` | Autenticado | `titulo`, `precio_kidos`, descripcion opcional |
| PATCH | `/market/items/{item_id}` | Vendedor o su padre | Titulo, descripcion, precio; solo DISPONIBLE |
| DELETE | `/market/items/{item_id}` | Vendedor o su padre | Retirar solo si DISPONIBLE; pasa a CANCELADO, conserva historial; 204 |
| POST | `/market/items/{item_id}/buy` | Autenticado | `cuenta_id` corriente propia; devuelve escrow |
| POST | `/market/items/{item_id}/confirm-delivery` | Parte implicada o su padre | Sin cuerpo; liberar pago |
| POST | `/market/items/{item_id}/cancel` | Parte implicada o su padre | Sin cuerpo; reembolsar |
| GET | `/market/history` | Autenticado | Escrows propios o de la familia visible |

Los articulos retirados no se muestran en el listado sin filtro; se pueden
consultar con `estado=CANCELADO` y por ID. No se pueden comprar ni editar.
Retirar un articulo en ESCROW o VENDIDO devuelve 409, sin mover fondos.

### Tareas y recompensas

| Metodo | Ruta | Permiso | Entrada / resultado |
|---|---|---|---|
| GET | `/tasks` | Autenticado | Tareas propias o de los hijos |
| POST | `/tasks` | Padre | `usuario_id`, `titulo`, `recompensa_kidos`, descripcion opcional |
| POST | `/tasks/{task_id}/complete` | Hijo asignado | Sin cuerpo; solicitar aprobacion |
| POST | `/tasks/{task_id}/approve` | Padre del hijo | `cuenta_id` corriente del hijo; abonar premio |
| DELETE | `/tasks/{task_id}` | Padre del hijo | Solo ASIGNADA; pendientes de aprobacion o aprobadas devuelven 409; 204 |

## Flujos funcionales

### 1. Alta familiar y primeros fondos

1. Registrar adulto mediante `POST /users/`:

   ```json
   {
     "nombre": "Alex",
     "apellidos": "Garcia",
     "email": "adulto@example.com",
     "rol": "PADRE",
     "password": "una-contrasena-propia"
   }
   ```

2. Iniciar sesion en `/auth/login/parent` y guardar el token.
3. Crear hijo en `/users/children` con el token del padre:

   ```json
   {
     "nombre": "Leo",
     "email": "leo@example.com",
     "rol": "NINO",
     "codigo_pin": "2468"
   }
   ```

4. Consultar `/accounts/me` y `/accounts/user/{hijo_id}` para obtener las cuentas.
5. Recargar al padre mediante `/transactions/deposito`.
6. Dar paga al hijo mediante `/transactions/paga`, con origen si se desea
   descontar del saldo del padre.
7. El hijo accede en `/auth/login/pin` con su ID y PIN.

Los emails de los ejemplos son ilustrativos. El esquema de alta actual exige
email tambien para los menores, aunque el modelo de base de datos admite null.

Para incorporar al segundo administrador, enviar a `POST /users/` con el token
del primero:

```json
{
  "nombre": "Maria",
  "email": "maria@example.com",
  "rol": "MADRE",
  "password": "una-contrasena-propia"
}
```

Tambien puede ser PADRE creado por MADRE. Los dos administran los miembros
existentes y futuros, tareas y ofertas de bonos de la misma familia.
Para un FAMILIAR, usar ese endpoint con `rol: "FAMILIAR"` y `codigo_pin`.
El frontend debe agrupar PADRE/MADRE como administradores y NINO/FAMILIAR como
miembros, incluyendo el bloqueo permanente en ambos roles de PIN.

### 2. QR y desbloqueo de PIN

1. El padre emite una tarjeta con `POST /users/{hijo_id}/cards`, cuerpo `{}`.
2. El frontend representa `qr_uuid` como QR o lo asocia a una tarjeta fisica.
3. El menor envia `{"qr_uuid": "...", "pin": "2468"}` al login.
4. Tras tres fallos, mostrar que debe contactar con su padre.
5. El padre consulta `/users/children`, detecta `bloqueado_por_pin: true` y
   ejecuta `POST /users/{hijo_id}/unlock`.

No intentar desbloquear por tiempo ni mediante PATCH de perfil.

#### Alternativa al QR: apodo y PIN

Al crear un NINO/FAMILIAR, el administrador puede incluir
`"nombre_usuario": "leo_7"` en el alta. Para asignarlo a un usuario existente,
enviar `PATCH /users/{user_id}` con su token PADRE/MADRE:

```json
{"nombre_usuario": "leo_7"}
```

El miembro puede entrar con `POST /auth/login/pin` sin recordar el codigo QR:

```json
{"nombre_usuario": "leo_7", "pin": "2468"}
```

El frontend debe ofrecer esta alternativa junto al escaneo QR. Si el apodo no
existe, se devuelve 404; formato invalido, 422; PIN incorrecto, 401, hasta el
bloqueo 403. Cambiar el apodo no reinicia los intentos ni desbloquea la cuenta.
QR e ID siguen disponibles aunque se borre el apodo.

### 3. Foto desde movil o webcam

1. Crear el usuario para obtener su ID.
2. Capturar foto con la interfaz del movil o `getUserMedia` en el frontend.
3. Convertirla en `File`/`Blob` JPEG, PNG o WebP.
4. Enviar el archivo autenticado:

   ```javascript
   const form = new FormData();
   form.append("file", foto, "foto.jpg");

   const response = await fetch(`${apiUrl}/api/v1/users/${userId}/avatar`, {
     method: "POST",
     headers: { Authorization: `Bearer ${token}` },
     body: form,
   });
   if (!response.ok) throw new Error("No se pudo subir la foto");
   const user = await response.json();
   ```

5. Usar `user.avatar_url`, una ruta relativa al backend, para descargar con token:

   ```javascript
   const response = await fetch(`${apiUrl}${user.avatar_url}`, {
     headers: { Authorization: `Bearer ${token}` },
   });
   if (!response.ok) throw new Error("No se pudo cargar la foto");
   const imageUrl = URL.createObjectURL(await response.blob());
   // Asignar imageUrl al src y liberar con URL.revokeObjectURL al dejar de usarlo.
   ```

No fijar manualmente `Content-Type` para FormData. Un `<img src>` directo a la
ruta privada no envia el header Bearer.

Limites: 5 MB, 20 megapixeles; salida JPEG hasta 512 x 512, orientacion corregida
y sin metadatos de camara. Se valida el contenido, no solo el MIME enviado.
Se almacena una unica foto por usuario en la base de datos, no el original.
Subir otra reemplaza la anterior. HEIC requiere conversion previa.
Enviar `{"avatar_url": null}` al PATCH de perfil elimina la foto.
La camara del navegador requiere permisos y HTTPS, salvo localhost.

### 4. Ahorro y metas

1. El padre crea una cuenta AHORRO para el hijo.
2. Establece su interes semanal con `/economy/savings-rate/{account_id}`.
3. Se transfieren fondos a esa cuenta.
4. El proceso periodico capitaliza semanas completas.
5. Crear una meta vinculada a una cuenta y aportar con `/goals/{id}/deposit`.
   La aportacion sale del saldo disponible y pasa al progreso de la meta.

### 5. Renta fija

1. El padre publica una oferta de bono.
2. El hijo consulta ofertas y compra con una cuenta propia y saldo suficiente.
3. Se descuenta el capital y se crea un bono ACTIVO con condiciones de la oferta.
4. Para cobrar, ejecutar `/bonds/{id}/redeem`:
   - Al vencer: devuelve capital + capital por tasa; estado COMPLETADO.
   - Antes de vencer: devuelve solo capital; estado RESCATADO, y registra como
     penalizacion el interes no cobrado.
5. Los fondos vuelven a la cuenta de origen. No se puede rescatar dos veces.

### 6. Bolsa, noticias y grafica

1. El padre crea un indice.
2. El usuario compra desde una cuenta corriente propia o gestionable.
3. Participaciones = importe invertido / precio de compra.
4. Las simulaciones semanales modifican el precio; no garantizan ganancias.
5. Las noticias cambian el precio sobre la base inicial:
   `nuevo = max(precio_actual + precio_base * impacto_pct / 100, 0.01)`,
   redondeado a dos decimales.
6. Si se omite `producto_id` o es null, la noticia afecta a todos los indices
   activos, no a los bonos. Para noticias globales los campos de precio
   anterior/resultante de la noticia son null.
7. Consultar `/investments/products/{id}/history` para dibujar la grafica:

   ```json
   [
     {"id": 1, "producto_id": 1, "precio_kidos": 100, "fecha": "2026-10-01T12:00:00Z"},
     {"id": 2, "producto_id": 1, "precio_kidos": 105, "fecha": "2026-10-08T12:00:00Z"}
   ]
   ```

8. Al vender, se ingresan `participaciones * precio_actual` en una cuenta
   corriente del propietario y la posicion queda LIQUIDADA.

El historico guarda el precio inicial, cada semana simulada y cada cambio por
noticia. Para productos antiguos se crea un punto con el ultimo precio conocido:
no se reconstruyen precios que nunca se guardaron.

### 7. Mercadillo y escrow

1. El vendedor publica un articulo/servicio DISPONIBLE.
2. El comprador selecciona una cuenta corriente propia.
3. Comprar descuenta el importe y lo mantiene en un escrow PENDIENTE; el articulo
   pasa a ESCROW. No se paga todavia al vendedor.
4. Comprador, vendedor o padre de una de las partes confirma la entrega:
   escrow CONFIRMADO, articulo VENDIDO y pago al vendedor.
5. Si se cancela antes de confirmar: escrow REEMBOLSADO, articulo DISPONIBLE y
   devolucion al comprador.
6. Consultar `/market/history` para el historial especifico de estas operaciones.

El destino del pago/reembolso lo selecciona el backend entre las cuentas del
usuario; no se solicita cuenta destino ni se garantiza devolver a la cuenta
exacta utilizada al comprar. Los movimientos se registran como escrows, no como
entradas del historial bancario general.

### 8. Tareas y recompensas

1. Padre: crear tarea asignada a un hijo concreto con premio positivo.
2. Hijo: marcarla completada.
3. Padre: revisar y aprobar eligiendo una cuenta corriente del hijo.
4. La aprobacion abona el premio y crea una transaccion RECOMPENSA.

```text
ASIGNADA -> PENDIENTE_APROBACION -> COMPLETADA
```

La tarea no se paga al marcarla completada. El premio es emision directa de
Kidos, no se descuenta de una cuenta del padre. Una segunda aprobacion se rechaza.
El padre solo puede eliminar tareas ASIGNADAS sin mover fondos. Las pendientes
de aprobacion y las aprobadas se conservan. No existen endpoints para rechazar,
editar o repetir tareas.

## Economia automatica

[economy_scheduler.py](app/services/economy_scheduler.py) comprueba los procesos
cada 60 segundos; eso no significa que se alteren precios cada minuto.
Se aplican periodos de **7 dias completos** mediante cursores persistidos.
Si el servidor estuvo parado, se recuperan los periodos pendientes.

| Proceso | Comportamiento |
|---|---|
| Indices | Simulacion semanal estocastica, volatilidad y rachas bajistas |
| Inflacion | Multiplica precios de articulos DISPONIBLES por `(1 + tasa)^semanas` |
| Ahorro | Abona `saldo * ((1 + tasa)^semanas - 1)` y registra INTERES |

La inflacion no resta dinero de las cuentas. Si no existe politica, no se aplica.
La actualizacion de su tasa procesa antes los periodos pendientes con la tasa
anterior; la de interes de ahorro liquida primero los periodos pendientes.
Los periodos de ahorro se calculan con el saldo existente cuando se ejecuta el
proceso, no mediante un historico diario de saldos.

No hay endpoint publico de simulacion manual. Los vencimientos de bonos, la
aprobacion de tareas y la confirmacion de escrow son acciones explicitas.

## Modelos y estados

Los modelos se registran en [app/db/base.py](app/db/base.py).

| Entidad | Responsabilidad / estados |
|---|---|
| User | Perfil, apodo unico opcional, rol, familia compartida, administrador creador, hash, intentos y bloqueo |
| UserAvatar | JPEG privado en base de datos, uno por usuario |
| QrCard | Identificador QR y estado activo/inactivo |
| Account | CORRIENTE, AHORRO o INVERSION |
| Transaction | DEPOSITO, RETIRO, TRANSFERENCIA, PAGA, INTERES, INVERSION, RECOMPENSA |
| BondOffer | Condiciones de bonos publicadas por padre |
| Bond | ACTIVO, COMPLETADO, RESCATADO |
| Goal | Progreso de ahorro y estado |
| InvestmentProduct | Activo global BONO o INDICE |
| UserInvestment | ACTIVA, LIQUIDADA, CANCELADA |
| InvestmentPriceHistory | Precio de producto y fecha |
| MarketNews | Noticia dirigida o global con impacto |
| InflationPolicy | Tasa y cursor de aplicacion |
| MarketItem | DISPONIBLE, ESCROW, VENDIDO, CANCELADO |
| EscrowTransaction | PENDIENTE, CONFIRMADO, CANCELADO, REEMBOLSADO |
| Task | ASIGNADA, PENDIENTE_APROBACION, COMPLETADA |
| PasswordResetToken | Token hasheado, caducidad y uso |

Que un tipo o estado exista en el modelo no implica que tenga un endpoint
publico para crearlo o cambiarlo.

## Integracion con el frontend

- Usar las rutas exactas de las tablas: algunas llevan barra final.
- Enviar Bearer en peticiones privadas; no enviar tokens en URLs.
- JSON para formularios y multipart solo para fotos.
- Tratar `200` con `null` en inflacion como "sin configurar".
- Un 204 no contiene JSON: no llamar a `response.json()` en esos casos.
- Los errores normalmente contienen `detail`; en validaciones puede ser un array.
- Tratar 401 de PIN como intento incorrecto y 403 de bloqueo como intervencion
  del padre. No mostrar cuenta atras para un menor bloqueado.
- Las tasas son decimales, excepto `impacto_pct` y `variacion_pct`, que son
  porcentajes: `impacto_pct: 5` significa cinco puntos sobre el precio base.
- Los importes positivos son Kidos. Los IDs son enteros.
- Las respuestas de fecha usan ISO 8601. PostgreSQL conserva zonas horarias donde
  el modelo las define; SQLite de pruebas puede devolver fechas sin zona.
- Las listas paginadas usan offset/limit, sin total. No todas las listas admiten
  paginacion: comprobar la tabla o OpenAPI.

Codigos frecuentes:

| Codigo | Significado |
|---|---|
| 200 | Consulta o modificacion correcta |
| 201 | Creacion correcta |
| 202 | Solicitud de recuperacion aceptada |
| 204 | Operacion correcta sin cuerpo |
| 400 | Regla de negocio, saldo o estado invalido |
| 401 | Autenticacion ausente/invalida o PIN incorrecto antes del bloqueo |
| 403 | Permisos insuficientes o usuario bloqueado |
| 404 | Recurso inexistente o no visible |
| 409 | Conflicto: nombre o apodo repetido, politica existente, eliminacion con saldo |
| 413 | Foto demasiado grande en bytes o pixeles |
| 422 | Campos o contenido de imagen invalidos |
| 500 | Error interno |
| 503 | Recuperacion por correo sin configuracion |

## Pruebas

Las herramientas de pruebas no estan todas declaradas en `requirements.txt`.
Para un entorno de desarrollo nuevo, instalar Pytest y HTTPX:

```powershell
.\venv\Scripts\python.exe -m pip install pytest httpx
.\venv\Scripts\python.exe -m pytest -q
```

Configuracion de fixtures: [tests/conftest.py](tests/conftest.py).
Se utiliza SQLite en memoria con sustitucion de la dependencia `get_db`.
El ciclo de vida de TestClient tambien inicia la aplicacion: la configuracion
de conexion debe apuntar a una base de datos **dedicada a desarrollo/pruebas**,
no a produccion.

Existe una interferencia de orden entre el override definido al importar
[test_api.py](tests/test_api.py) y los overrides de conftest, que se limpian tras
cada prueba. Si se combinan modulos en ciertos ordenes, pueden fallar logins
por usar bases de datos diferentes. Ejecutar ese modulo por separado:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\test_api.py
.\venv\Scripts\python.exe -m pytest -q tests --ignore=tests\test_api.py
```

Si plugins instalados globalmente interfieren, deshabilitar su carga automatica
en la sesion de pruebas:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
.\venv\Scripts\python.exe -m pytest -q tests\test_pin_limits.py
```

Los tests SQLite no demuestran por si solos el comportamiento concurrente de
PostgreSQL. El test de PIN comprueba la generacion de `FOR UPDATE`, pero una
validacion de concurrencia real requiere PostgreSQL y sesiones independientes.

## Alcance actual y consideraciones operativas

- Las rutas documentadas son las registradas en
  [router.py](app/api/v1/router.py) y el OpenAPI generado.
- [tpv.py](app/api/v1/endpoints/tpv.py) existe, pero no esta incluido en el router:
  no hay API TPV publicada actualmente.
- No hay `/investments/simulate` publico, refresh de JWT, cierre de sesion con
  revocacion de token ni retirada bancaria generica publicada.
- El registro publico permite crear adultos en familias independientes; no esta
  restringido automaticamente al primer adulto.
- Los catalogos de mercado, inversiones y noticias, y la politica de inflacion,
  son globales. No asumir aislamiento familiar de esos recursos.
- Los hashes no se incluyen en las respuestas. Las fotos privadas requieren
  autenticacion y se sirven con `Cache-Control: private, no-store`.
- El bloqueo es por usuario, no un limite general de peticiones por IP.
- Usar HTTPS, una SECRET_KEY propia y CORS con los origenes reales.
- Respaldar PostgreSQL: tambien contiene las fotos, historicos y cursores.
- [compatibility.py](app/db/compatibility.py) aplica cambios aditivos al iniciar;
  no sustituye un sistema completo de migraciones versionadas. Respaldar y
  comprobar los cambios antes de actualizar una instalacion existente.
  Incluye `CANCELADO` en el enum PostgreSQL `marketstatus` para retirar articulos.
  Se ejecuta antes de atender peticiones y es idempotente. Si la base se administra
  con migraciones externas, aplicar y confirmar antes de desplegar:

  ```sql
  ALTER TYPE marketstatus ADD VALUE IF NOT EXISTS 'CANCELADO';
  ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'MADRE';
  ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'FAMILIAR';
  ```

  Los nuevos valores del enum se confirman antes del backfill de `familia_id`.
  Tambien se agrega `nombre_usuario` nullable y su indice unico sin distinguir
  mayusculas; no se generan apodos automaticamente ni se modifican los PIN.
  Los adultos existentes mantienen familias independientes; sus miembros
  heredan la familia segun `padre_id`. Los miembros sin vinculo permanecen
  aislados. Las familias ya asignadas no se sobrescriben al reiniciar.
  La cuenta PostgreSQL utilizada para las actualizaciones debe tener permisos
  para alterar esos tipos y la tabla usuarios. Una actualizacion fallida impide el arranque.
- Cada proceso de aplicacion inicia un scheduler. Para despliegues con multiples
  workers/replicas, planificar y validar la coordinacion de tareas periodicas.
- Los importes actuales utilizan Float: es una simulacion educativa, no un
  sistema contable de dinero real.
- Consultar `/openapi.json` como fuente de contratos vigente al integrar nuevos
  formularios o generar clientes.
