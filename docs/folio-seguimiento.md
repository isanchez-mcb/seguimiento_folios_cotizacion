# Endpoints de Cotización — Folios y Datos de Contacto

Todos los endpoints de este documento usan HTTP Basic Auth (igual que el resto de la API).

- [POST /cotizacion/folio-seguimiento](#post-cotizacionfolio-seguimiento)
- [GET /cotizacion/datos-contacto](#get-cotizaciondatos-contacto)

---

## POST /cotizacion/folio-seguimiento

Crea un folio de seguimiento (Case) en Salesforce a partir del expediente de un colaborador. Dependiendo de si se encuentra o no una póliza asociada, el folio queda registrado como **Mantenimiento** (duplicado/facturas) o como **Contacto** (folio de contingencia).

---

### Request

```json
{
  "expediente_colaborador": "string (requerido)",
  "tipo_movimiento": "Duplicado | Facturas (requerido)",
  "numero_poliza": "string (opcional)",
  "ramo": "string (opcional, ej. 'GMM')",
  "correo": "string (opcional)",
  "telefono": "string (opcional)",
  "origen_folio": "string (opcional, default: 'Lucia')"
}
```

| Campo | Tipo | Requerido | Notas |
|---|---|---|---|
| `expediente_colaborador` | string | Sí | Se usa para localizar la cuenta en Salesforce. |
| `tipo_movimiento` | string | Sí | Solo acepta `"Duplicado"` o `"Facturas"`. Cualquier otro valor es rechazado. |
| `numero_poliza` | string | No | Si se omite o viene vacío, se crea directamente un folio de Contacto (ver más abajo). |
| `ramo` | string | No | Si es `"GMM"`, cambia la forma en que se busca la póliza (formato `"maestra-certificado"`). |
| `correo` / `telefono` | string | No | Se usan solo para armar la nota de contacto del folio. Se recomienda enviar al menos uno. |
| `origen_folio` | string | No | Se usa como `Origin` del Case y como título de la nota. Si viene vacío, se usa `"Lucia"`. |

---

### Respuestas posibles

#### 1. Éxito — Folio de Mantenimiento (con póliza encontrada)

Ocurre cuando se envía `numero_poliza` y la póliza se localiza en la cuenta.

```json
{
  "case_id": "500XXXXXXXXXXXXAAA",
  "case_number": "00012345",
  "case_link": "https://.../lightning/r/Case/500XXXXXXXXXXXXAAA/view",
  "mensaje": "Folio de seguimiento creado exitosamente. Asesor asignado: Juan Pérez"
}
```
**HTTP 200**

#### 2. Éxito — Folio de Contacto (sin póliza)

Ocurre cuando **no se envía** `numero_poliza`, o se envía pero **no se encuentra** en la cuenta. Ya no es un error: se crea automáticamente un folio de tipo `9.- Contacto`, asociado solo a la cuenta (sin datos de póliza, tipo de movimiento u oficina).

```json
{
  "case_id": "500YYYYYYYYYYYYAAA",
  "case_number": "00012346",
  "case_link": "https://.../lightning/r/Case/500YYYYYYYYYYYYAAA/view",
  "mensaje": "Folio de seguimiento creado exitosamente. Asesor asignado: María López"
}
```
**HTTP 200**

> El frontend **no puede distinguir** por el response si el folio creado fue de Mantenimiento o de Contacto — la forma de la respuesta es idéntica en ambos casos. Si se necesita diferenciarlo en la UI, hay que solicitarlo como campo adicional.

#### 3. Éxito — Sin asesor disponible en ese momento

Si no hay ningún asesor activo/disponible (Omni-Channel) en la cola `Ejecutivos SAC`, el folio igual se crea y se asigna a un propietario de respaldo, pero el mensaje lo indica:

```json
{
  "case_id": "500ZZZZZZZZZZZZAAA",
  "case_number": "00012347",
  "case_link": "https://.../lightning/r/Case/500ZZZZZZZZZZZZAAA/view",
  "mensaje": "Folio de seguimiento creado exitosamente. Pronto se le asignará un asesor"
}
```
**HTTP 200**

---

### Errores

| HTTP | Cuándo ocurre | `detail` (ejemplo) |
|---|---|---|
| 401 | Credenciales de Basic Auth inválidas o ausentes. | `"Incorrect email or password"` |
| 404 | No se encontró ninguna cuenta con el `expediente_colaborador` enviado (ni siquiera con las variaciones de ceros a la izquierda). | `"No se encontró cuenta con el expediente: {expediente}"` |
| 422 | El body no cumple el esquema (falta `expediente_colaborador`/`tipo_movimiento`, o `tipo_movimiento` no es `"Duplicado"`/`"Facturas"`). | Error estándar de validación de FastAPI/Pydantic. |
| 500 | Error al crear el Case en Salesforce, al obtener el RecordType, o cualquier error inesperado (incluyendo una sesión de Salesforce expirada a mitad del proceso). | `"Error del servidor: {mensaje técnico}"` |

**Notas para el frontend sobre el 500:**
- No es necesariamente un error del lado del usuario — puede ser un problema transitorio de sesión con Salesforce. Un reintento del mismo request suele resolverlo.
- No se debe reintentar automáticamente sin límite (para evitar folios duplicados si el error ocurrió después de haber creado el Case pero antes de responder). Se recomienda un solo reintento manual.

**Nota general:** ya no existe un 404 por "póliza no encontrada" — ese escenario ahora siempre resulta en un folio de Contacto (ver caso de éxito #2), nunca en un error.

---

## GET /cotizacion/datos-contacto

Consulta los datos de contacto (correo y teléfono) registrados en la cuenta de Salesforce asociada a un expediente, sin crear ni modificar nada. Pensado para prellenar/validar datos antes de mostrar un formulario (por ejemplo, antes de llamar a `/cotizacion/folio-seguimiento`).

### Request

Parámetro de query (no hay body, es un `GET`):

```
GET /cotizacion/datos-contacto?expediente_colaborador=12345
```

| Campo | Tipo | Requerido | Notas |
|---|---|---|---|
| `expediente_colaborador` | string (query param) | Sí | Se busca con la misma búsqueda en cascada (exacto → variaciones de ceros) que el resto de endpoints. |

### Respuestas posibles

Todas devuelven **HTTP 200** con la misma forma; solo cambia el contenido de `mensaje` según qué datos tenga la cuenta:

#### 1. Cuenta con correo y teléfono

```json
{
  "expediente_buscado": "12345",
  "nombre_cuenta": "Juan Pérez",
  "correo": "juan.perez@ejemplo.com",
  "telefono": "+525512345678",
  "mensaje": "Datos de contacto encontrados"
}
```

#### 2. Cuenta con correo pero sin teléfono

```json
{
  "expediente_buscado": "12345",
  "nombre_cuenta": "Juan Pérez",
  "correo": "juan.perez@ejemplo.com",
  "telefono": null,
  "mensaje": "La cuenta no tiene teléfono registrado"
}
```

#### 3. Cuenta con teléfono pero sin correo

```json
{
  "expediente_buscado": "12345",
  "nombre_cuenta": "Juan Pérez",
  "correo": null,
  "telefono": "+525512345678",
  "mensaje": "La cuenta no tiene correo registrado"
}
```

#### 4. Cuenta sin correo ni teléfono

```json
{
  "expediente_buscado": "12345",
  "nombre_cuenta": "Juan Pérez",
  "correo": null,
  "telefono": null,
  "mensaje": "La cuenta no tiene datos de contacto"
}
```

> El frontend debe decidir su comportamiento leyendo `correo`/`telefono` directamente (ambos son `null` cuando no existen) — el campo `mensaje` es solo texto informativo para mostrar al usuario, no un código de estado a parsear.

### Errores

| HTTP | Cuándo ocurre | `detail` (ejemplo) |
|---|---|---|
| 401 | Credenciales de Basic Auth inválidas o ausentes. | `"Incorrect email or password"` |
| 400 | `expediente_colaborador` viene vacío o solo con espacios (pero el parámetro sí llegó). | `"expediente_colaborador es requerido"` |
| 404 | No se encontró ninguna cuenta con ese expediente (ni con las variaciones de ceros). | `"No se encontró cuenta con el expediente: {expediente}"` |
| 422 | El parámetro `expediente_colaborador` no se envió en absoluto en el query string. | Error estándar de validación de FastAPI (parámetro requerido faltante). |
| 500 | Error inesperado de Salesforce (sesión expirada, error de red, etc.). | ⚠️ Ver nota abajo — **no** trae el formato `"Error del servidor: ..."`. |

**⚠️ Nota importante para el frontend:** a diferencia de `/cotizacion/folio-seguimiento` y del resto de la API, este endpoint **no envuelve sus operaciones en un try/except**. Si Salesforce falla de forma inesperada (por ejemplo, sesión expirada), el 500 que se recibe es el genérico de FastAPI (`{"detail": "Internal Server Error"}`), no el mensaje descriptivo `"Error del servidor: {detalle}"` que sí devuelven los demás endpoints. No hay que asumir que todo 500 en esta API trae el mismo formato de `detail`.
