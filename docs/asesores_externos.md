# Asesores Externos — Documentación para Frontend

Rama: `asesores_qr`. Dos endpoints: uno para validar que un asesor externo esté activo (pensado para el flujo de código QR), y otro para registrar un prospecto capturado en campo.

## Autenticación

Ambos endpoints requieren **HTTP Basic Auth** (usuario/contraseña del sistema, no del asesor). Si las credenciales son incorrectas o faltan, responden `401 Unauthorized`.

```
Authorization: Basic base64(usuario:password)
```

---

## 1. `GET /asesores-externos/buscar`

Busca un asesor externo por su número y valida que tenga una cuenta de usuario activa en Salesforce. Úsalo para verificar el asesor **antes** de mostrar el formulario de captura (por ejemplo, al escanear el QR).

### Query params

| Parámetro | Tipo | Requerido | Descripción |
|---|---|---|---|
| `numero_asesor` | string | Sí | Número/alias del asesor a buscar. |

### Respuesta `200 OK`

```json
{
  "Name": "Juan Pérez",
  "Numero_de_asesor__c": "12345",
  "Puesto__c": "Asesor",
  "Zona__c": "Centro",
  "Correo_electronico__c": "juan.perez@ejemplo.com",
  "Numero_telefonico__c": "5511112222"
}
```

Todos los campos son `string | null`.

### Errores

| Código | Cuándo |
|---|---|
| `400` | `numero_asesor` vacío o no enviado. |
| `404` | No existe un `Asesor_externo__c` con ese número. |
| `404` | El asesor existe pero **no tiene una cuenta de usuario activa** en Salesforce (mensaje explícito pidiendo verificar con el administrador). |
| `401` | Credenciales de Basic Auth inválidas. |

---

## 2. `POST /asesores-externos/lead/crear`

Registra un prospecto capturado en campo (formulario vía QR) y lo asigna en Salesforce. Internamente puede terminar creando un **Lead**, una **Opportunity**, o solo una **tarea de seguimiento**, dependiendo de si la persona ya existe en Salesforce (ver sección de contingencias). El frontend siempre recibe una respuesta `200` con el resultado, sin necesidad de conocer cuál de los tres casos ocurrió.

### Request body

```json
{
  "nombre": "María",
  "apellido_paterno": "López",
  "apellido_materno": "García",
  "fecha_nacimiento": "1990-05-20",
  "genero": "F",
  "email": "maria@ejemplo.com",
  "telefono": "5533334444",
  "empresa": "STRM",
  "expediente_colaborador": "EXP123",
  "company": null,
  "seguros": ["Autos", "Vida"],
  "numero_asesor": "12345"
}
```

| Campo | Tipo | Requerido | Notas |
|---|---|---|---|
| `nombre` | string | Sí | |
| `apellido_paterno` | string | Sí | |
| `apellido_materno` | string | No | Se concatena al apellido paterno si viene. |
| `fecha_nacimiento` | date (`YYYY-MM-DD`) | Sí | |
| `genero` | string | Sí | |
| `email` | string | Sí | Se usa también para el correo de confirmación al cliente. |
| `telefono` | string | Sí | |
| `empresa` | string | No | Ver tabla de códigos abajo. `null`, `""` o `"NN"` = Nuevos Negocios. |
| `expediente_colaborador` | string | **Condicional** | Obligatorio solo si `empresa = "STRM"` (ver validaciones). |
| `company` | string | **Condicional** | Obligatorio solo si `seguros` corresponde a un caso de Persona Moral (ver más abajo). |
| `seguros` | string[] | Sí | Valores válidos dependen de `empresa` — ver catálogos abajo. |
| `numero_asesor` | string | Sí | Debe existir y estar activo (mismo asesor que valida `/buscar`). |

#### Códigos de `empresa`

| Código | Se traduce a (`Negocio__c`) | ¿Requiere `expediente_colaborador`? |
|---|---|---|
| `"STRM"` | `SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA` | **Sí** |
| `"BIMBO"` | `GRUPO BIMBO, S.A.B. DE C.V.` | No |
| `""` / `"NN"` / `null` | (ninguno — flujo Nuevos Negocios) | No |

> El catálogo vive en `app/utils/diccionarios.py` (`negocios_lead_campo.MAPEO`). Agregar un negocio nuevo solo requiere una entrada ahí, sin tocar el resto del código.

#### Catálogo de `seguros` (determina el tipo de prospecto)

El backend usa los valores de `seguros` para decidir automáticamente si el prospecto es **Masivo**, **Persona física - Nuevos negocios** o **Persona moral - Nuevos negocios**. El frontend debe mostrar el set correcto según el valor de `empresa`:

**A) `empresa = "STRM"` o `"BIMBO"` (Masivo)** — selección múltiple:

| Valor en `seguros` | Ramo interno |
|---|---|
| `Gastos Medicos Mayores` | ACCIDENTES Y ENFERMEDADES |
| `Autos` | DAÑOS |
| `Vida` | VIDA |
| `Hogar` | DAÑOS |

**B) `empresa = "NN"` / vacío, persona física** — selección múltiple:

| Valor en `seguros` | Ramo interno |
|---|---|
| `Hogar` | DAÑOS |
| `Gastos Medicos Mayores` | ACCIDENTES Y ENFERMEDADES |
| `Gastos Medicos Menores` | ACCIDENTES Y ENFERMEDADES |
| `Autos` | DAÑOS |
| `Vida` | VIDA |
| `Viajes` | ACCIDENTES Y ENFERMEDADES |
| `Responsabilidad Civil General` | DAÑOS |
| `Responsabilidad Civil Profesional` | DAÑOS |
| `Mascotas` | DAÑOS |
| `Transporte de mercancías` | DAÑOS |

**C) `empresa = "NN"` / vacío, persona moral** — el frontend debe mostrar estas dos opciones en una pantalla/flujo distinto (persona moral), y en ese caso **`company` es obligatorio**:

| Valor en `seguros` | Ramo(s) interno(s) |
|---|---|
| `Protección para mi empresa` | DAÑOS |
| `Protección para mis empleados` | ACCIDENTES Y ENFERMEDADES **y** VIDA |

> Los textos deben coincidir **exactamente** (mayúsculas, tildes) con los de las tablas — si el frontend envía un valor no reconocido para el tipo de negocio correspondiente, el backend responde `400`.
>
> El backend detecta "persona moral" automáticamente si `seguros` contiene alguno de los valores de la tabla C — no hace falta un campo aparte para indicarlo. Por eso no se deben mezclar valores de la tabla B y C en la misma solicitud.
>
> Catálogos en `app/utils/diccionarios.py` (`ramos_lead_campo`).

### Respuesta `200 OK`

```json
{
  "lead_id": "00Q5f000001ABCDE",
  "nombre_completo": "María López García",
  "asesor_asignado": "Juan Pérez",
  "asesor_telefono": "5511112222",
  "asesor_correo": "juan.perez@ejemplo.com"
}
```

| Campo | Notas |
|---|---|
| `lead_id` | Id del registro creado en Salesforce. **Puede ser un Lead o una Opportunity** (o el Id de un Lead ya existente), según el caso — ver contingencias. El nombre del campo se mantiene por compatibilidad. |
| `nombre_completo` | Nombre + apellidos del prospecto. |
| `asesor_asignado` | Nombre del asesor externo (`numero_asesor`), **no necesariamente quien queda como owner en Salesforce**. |
| `asesor_telefono` / `asesor_correo` | Datos de contacto del asesor externo, para mostrarlos en el frontend tras el registro. |

### Qué pasa "por debajo" (no requiere manejo especial del frontend, informativo)

1. Se valida `expediente_colaborador` (si aplica) y `company` (si aplica) — errores `400` si faltan.
2. Se busca el asesor externo — `404` si no existe.
3. **Asignación de owner en Salesforce** (no visible en la respuesta):
   - Masivo (STRM/BIMBO): si el asesor tiene cuenta de usuario activa, él es el owner; si no, se asigna a un owner de respaldo.
   - Nuevos negocios (física o moral): siempre se asigna al owner de respaldo.
   - En todos los casos, el campo `Asesor_externo__c` del registro queda con el asesor real capturado.
4. **Contingencias por duplicado** (transparentes para el frontend, siempre responde `200`):
   - Si Salesforce detecta que la persona **ya es cliente** (cuenta existente) → se crea una **Opportunity** en esa cuenta en vez de un Lead nuevo.
   - Si Salesforce detecta que **ya existe un prospecto (Lead)** con esos datos → no se duplica nada; solo se agrega una **tarea de seguimiento** sobre ese Lead con los datos de la nueva solicitud.
5. Se crea una nota con los seguros de interés, una tarea de seguimiento para el owner, y se envía un **correo de confirmación al `email`** del request con los datos de contacto del asesor asignado.

### Errores

| Código | Cuándo |
|---|---|
| `400` | Falta `expediente_colaborador` cuando `empresa = "STRM"`. |
| `400` | Falta `company` cuando `seguros` corresponde a persona moral. |
| `400` | Algún valor de `seguros` no es válido para el tipo de negocio resuelto. |
| `404` | `numero_asesor` no corresponde a ningún asesor externo. |
| `402` | Salesforce detectó un duplicado y no se pudo resolver automáticamente (caso residual, poco común). |
| `500` | Error interno / RecordType no configurado en el entorno de Salesforce. |
| `401` | Credenciales de Basic Auth inválidas. |

---

## Ejemplos de request por escenario

Payloads reales de prueba para `POST /lead/crear`, uno por cada camino que puede tomar el backend.

### Prospecto Masivo — STRM (crea Lead nuevo, RecordType `Masivo`)

```json
{
  "nombre": "Jesus Emmanuel",
  "apellido_paterno": "Salgado",
  "apellido_materno": "Lezama",
  "fecha_nacimiento": "2000-03-12",
  "genero": "M",
  "email": "jsalgado@mcbrokers.com.mx",
  "telefono": "+522211112145",
  "empresa": "STRM",
  "expediente_colaborador": "2000312",
  "seguros": ["Autos", "Vida"],
  "numero_asesor": "184"
}
```

### Prospecto Masivo — BIMBO (crea Lead nuevo, RecordType `Masivo`)

```json
{
  "nombre": "Yohary",
  "apellido_paterno": "Diaz",
  "apellido_materno": "Jimenez",
  "fecha_nacimiento": "2002-04-12",
  "genero": "M",
  "email": "ydiaz@mcbrokers.com.mx",
  "telefono": "+522211112010",
  "empresa": "Bimbo",
  "expediente_colaborador": "20020412",
  "seguros": ["Gastos Medicos Mayores", "Hogar"],
  "numero_asesor": "184"
}
```

> `empresa` no distingue mayúsculas/minúsculas (`"Bimbo"` se normaliza igual que `"BIMBO"`).

### Contingencia Opportunity — STRM (la persona ya es cliente → crea Opportunity en vez de Lead)

```json
{
  "nombre": "CARLOS ALBERTO",
  "apellido_paterno": "SANCHEZ",
  "apellido_materno": "XINAXTLE",
  "fecha_nacimiento": "2002-05-10",
  "genero": "M",
  "email": "isanchez@gmail.com",
  "telefono": "+521234567890",
  "empresa": "STRM",
  "expediente_colaborador": "1108197",
  "seguros": ["Vida"],
  "numero_asesor": "184"
}
```

### Contingencia Opportunity — BIMBO (misma lógica, otro negocio)

```json
{
  "nombre": "ALAN JOSEPH",
  "apellido_paterno": "SANCHEZ",
  "apellido_materno": "RAMIREZ",
  "fecha_nacimiento": "1970-08-11",
  "genero": "M",
  "email": "isanchez@gmail.com",
  "telefono": "+521234589090",
  "empresa": "Bimbo",
  "expediente_colaborador": "16183368",
  "seguros": ["Gastos Medicos Mayores", "Hogar"],
  "numero_asesor": "184"
}
```

> En ambos casos, la respuesta sigue siendo `200` — el `lead_id` de la respuesta es en realidad el Id de la Opportunity creada, no de un Lead.

### Nuevos Negocios — Persona física

```json
{
  "nombre": "Yohary",
  "apellido_paterno": "Diaz",
  "apellido_materno": "Jimenez",
  "fecha_nacimiento": "1997-01-28",
  "genero": "M",
  "email": "cjacome@mcbrokers.com.mx",
  "telefono": "+522211112010",
  "seguros": [
    "Gastos Medicos Mayores", "Hogar", "Gastos Medicos Menores", "Viajes",
    "Responsabilidad Civil General", "Responsabilidad Civil Profesional",
    "Mascotas", "Transporte de mercancías"
  ],
  "numero_asesor": "184"
}
```

> Sin `empresa` (ni `expediente_colaborador`, ni `company`) — el backend resuelve solo con `seguros` que es Persona física - Nuevos negocios.

### Nuevos Negocios — Persona moral

```json
{
  "nombre": "Jesus Emmanuel",
  "apellido_paterno": "Salgado",
  "apellido_materno": "Lezama",
  "fecha_nacimiento": "2000-12-03",
  "genero": "M",
  "email": "jsalgado@mcbrokers.com.mx",
  "telefono": "+522211232145",
  "company": "Luciernaga",
  "seguros": ["Protección para mi empresa", "Protección para mis empleados"],
  "numero_asesor": "184"
}
```

> Aquí `company` es obligatorio porque `seguros` coincide con el catálogo de persona moral (tabla C).

---

## Resumen rápido para el formulario de campo

1. El frontend escanea el QR → llama `GET /buscar` con el número de asesor → si `200`, muestra el formulario; si `404`, muestra el error correspondiente.
2. El usuario elige negocio (`STRM` / `BIMBO` / `NN`).
3. Según el negocio:
   - `STRM`/`BIMBO`: mostrar catálogo A, pedir `expediente_colaborador` (obligatorio para STRM).
   - `NN`: preguntar si es persona física o moral → mostrar catálogo B o C respectivamente. Si es moral, pedir también `company`.
4. Enviar `POST /lead/crear` con los datos capturados.
5. Mostrar al usuario los datos de contacto del asesor (`asesor_asignado`, `asesor_telefono`, `asesor_correo`) que vienen en la respuesta — el cliente también recibirá esa misma información por correo.
