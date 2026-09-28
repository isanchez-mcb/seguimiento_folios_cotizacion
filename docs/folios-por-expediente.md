# GET /folios/buscar-por-expediente

Todos los endpoints de este documento usan HTTP Basic Auth (igual que el resto de la API).

Busca la cuenta asociada a un expediente/colaborador en Salesforce y devuelve el listado resumido de todos sus folios (Cases), sin crear ni modificar nada.

---

## Request

Parámetros de query (no hay body, es un `GET`):

```
GET /folios/buscar-por-expediente?expediente=12345&empresa=STRM
```

| Campo | Tipo | Requerido | Notas |
|---|---|---|---|
| `expediente` | string (query param) | Sí | Número de expediente/colaborador (o RFC, según la empresa — ver tabla de normalización). |
| `empresa` | string (query param) | Sí | Código corto de la empresa. Se compara sin distinguir mayúsculas/minúsculas. Determina cómo se normaliza `expediente` antes de buscar. |

### Normalización de `expediente` según `empresa`

Antes de buscar la cuenta, `expediente` se ajusta al tamaño esperado para la empresa recibida:

| `empresa` | Tamaño esperado | Tipo de ajuste |
|---|---|---|
| `STRM` | 7 | Numérico: si es más corto se rellena con ceros a la izquierda; si es más largo (ceros de más) se le quitan. |
| `BIMBO` | 5 | Numérico (igual que arriba). |
| `CTBR` | 8 | Numérico (igual que arriba). |
| `CAJA` | 5 | Numérico (igual que arriba). |
| `EMP_STRM` | 6 | Numérico (igual que arriba). |
| `TEC` | 8 | Numérico (igual que arriba). |
| `MAC` | 10 | RFC: si es más corto se rellena con ceros a la izquierda; si es más largo (RFC completo de 13 con homoclave) se recorta a los primeros 10 caracteres. |
| `OTROS` | 10 | RFC (igual que `MAC`). |

Si `empresa` no coincide con ninguno de estos códigos, `expediente` se usa tal cual fue recibido, sin normalizar.

**Búsqueda en cascada:** primero se busca la cuenta con el `expediente` ya normalizado. Si no se encuentra (y el valor normalizado es distinto del original), se reintenta una vez más con el `expediente` **tal cual fue recibido**, como última alternativa.

---

## Respuesta exitosa

**HTTP 200**

```json
{
  "expediente_buscado": "12345",
  "empresa": "STRM",
  "account_id": "001WR000005ABCDYAW",
  "nombre_cuenta": "Juan Pérez",
  "folios": [
    {
      "CaseNumber": "00036408",
      "Estado": "Solicitud Finalizada",
      "Tipo_movimiento": "Reembolso",
      "Tipo": "Siniestros GMM",
      "Fecha_creacion": "2025-06-09T07:03:40Z"
    },
    {
      "CaseNumber": "00161371",
      "Estado": "Recibido",
      "Tipo_movimiento": "Duplicado",
      "Tipo": "Contacto",
      "Fecha_creacion": "2026-09-28T02:15:57Z"
    }
  ]
}
```

> **Nota:** este endpoint no incluye `Poliza_asociada` en la respuesta (a diferencia del servicio de referencia `/cuentas/folios`) — decisión permanente, no es un campo pendiente.

Si la cuenta existe pero no tiene folios, `folios` viene como lista vacía (`[]`), igual con HTTP 200 (no es un error).

### Campos de cada folio en `folios`

| Campo | Tipo | Notas |
|---|---|---|
| `CaseNumber` | string | Número de folio. |
| `Estado` | string | Ya traducido a la etiqueta "amigable" para el cliente (`Recibido`, `Validando Referencias`, `Procesando Solicitud`, `En espera de Respuesta`, `Solicitud Finalizada`). Si el tipo de folio no tiene un mapeo de traducción configurado, se muestra el status crudo de Salesforce tal cual. |
| `Tipo_movimiento` | string \| null | Para folios de Contacto, se resuelve desde el motivo registrado (ej. `"Duplicado"`, `"Estado Cuenta"`); puede venir `null` si el folio de Contacto no tiene un motivo asociado. Para el resto de folios, es el tipo de movimiento capturado en el Case. |
| `Tipo` | string | Tipo de folio sin el prefijo numérico de Salesforce (ej. `"Emisión"`, `"Mantenimiento"`, `"Siniestros GMM"`, `"Contacto"`). |
| `Fecha_creacion` | datetime (ISO 8601) | Fecha de creación del folio. |

**Notas de comportamiento:**
- El listado incluye folios de **Contacto** (`9.- Contacto`).
- El listado **excluye** folios de **Posible cancelación** (`7.- Posible cancelación`).
- Los folios vienen ordenados por fecha de creación descendente (más reciente primero).

---

## Errores

| HTTP | Cuándo ocurre | `detail` (ejemplo) |
|---|---|---|
| 401 | Credenciales de Basic Auth inválidas o ausentes. | `"Incorrect email or password"` |
| 404 | No se encontró ninguna cuenta con ese expediente/empresa (ni con el expediente normalizado ni con el recibido tal cual). | `"No se encontró una cuenta asociada a ese expediente"` |
| 422 | Falta `expediente` o `empresa` en el query string. | Error estándar de validación de FastAPI (parámetro requerido faltante). |
| 500 | Error inesperado de Salesforce (sesión expirada, error de red, etc.). | Error genérico de FastAPI/Salesforce. |
