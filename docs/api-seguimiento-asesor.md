# API de Trazabilidad de Asesor — `GET /api/v1/seguimiento/asesor`

Documentación de consumo para frontend. Endpoint de **solo lectura** (no crea ni modifica nada en Salesforce) que devuelve la trazabilidad end-to-end de un asesor: sus prospectos (Leads), oportunidades, folios de emisión (Cases) y pólizas, junto con KPIs agregados y paginación.

Código fuente: [`app/api/endpoints/seguimiento.py`](../app/api/endpoints/seguimiento.py), lógica en [`app/services/trazabilidad_asesor.py`](../app/services/trazabilidad_asesor.py), modelos de respuesta en [`app/models/schemas.py`](../app/models/schemas.py).

---

## 1. Autenticación

El endpoint requiere **HTTP Basic Auth** (`app/dependencias/security.py`). Hay que enviar el header `Authorization: Basic <base64(usuario:password)>` en cada request; las credenciales se validan contra `BASIC_AUTH_USERNAME` / `BASIC_AUTH_PASSWORD` del entorno.

Si las credenciales son incorrectas o faltan, responde `401 Unauthorized`.

---

## 2. Endpoint

```
GET /api/v1/seguimiento/asesor
```

La URL base depende del entorno donde esté desplegado el servicio (sandbox/producción); no está fijada en el código de este endpoint.

---

## 3. Parámetros de consulta (query params)

| Parámetro | Tipo | Obligatorio | Valores válidos / formato | Descripción |
|---|---|---|---|---|
| `numero_asesor` | string | **Sí** | — | Número del asesor (coincide con el `Alias` del `User` en Salesforce, o con `Numero_de_asesor__c` en `Asesor_externo__c` si no tiene usuario activo). No puede ir vacío. |
| `status_lead` | string | No | `Nuevo`, `Stand by`, `Convertido`, `No convertido` | Filtra los prospectos por su `Status` exacto en Salesforce. **Importante:** ver sección 4, cambia el universo de oportunidades que se consultan. |
| `stage_opp` | string | No | `Nueva`, `Cotización`, `Proceso de cierre`, `Cerrado ganado`, `Póliza emitida`, `Póliza no emitida`, `Concluido`, `Otros` | Filtra por la etapa (`StageName`) de la oportunidad. `Otros` es un valor especial: no existe como tal en Salesforce, agrupa cualquier etapa que no esté en la lista anterior (etapas inactivas o de versiones anteriores del negocio). |
| `fecha_inicio` | string (`YYYY-MM-DD`) | No | — | Filtra registros con `CreatedDate >=` esta fecha. Se aplica en la consulta a Salesforce sobre Leads y Oportunidades (no sobre folios). |
| `fecha_fin` | string (`YYYY-MM-DD`) | No | — | Filtra registros con `CreatedDate <=` esta fecha. Misma lógica que `fecha_inicio`. |
| `periodo` | string | No | `YYYY-MM` o `YYYY-MM:YYYY-MM` (rango) | Filtro alterno de fecha, aplicado **después** de traer los datos. Incluye un registro si el Lead, la Oportunidad **o alguna Póliza/Folio** fue creado dentro del periodo. Es independiente de `fecha_inicio`/`fecha_fin` — puedes usar uno u otro según si necesitas rango exacto (`fecha_inicio`/`fecha_fin`) o mes calendario con cobertura de folios (`periodo`). |
| `con_folio` | boolean | No | `true` / `false` | Si `true`, solo regresa items que ya tienen al menos un folio de emisión. Si `false`, solo items sin folios. Se aplica al final, después de todos los demás filtros. |
| `page` | int | No | `>= 0` (por defecto `0`) | Índice de página, base cero. |
| `size` | int | No | `1` a `100` (por defecto `10`) | Cantidad de registros por página. |

Valores inválidos en `status_lead` o `stage_opp` devuelven `400 Bad Request` con el detalle de los valores permitidos.

---

## 4. Comportamiento importante de los filtros

- **`status_lead` cambia qué oportunidades se consultan.** Si se envía `status_lead`, el servicio solo trae las oportunidades **vinculadas a los leads que cumplen ese status** (es decir, leads convertidos con ese status). Si **no** se envía `status_lead`, el servicio trae **todas** las oportunidades del asesor, incluyendo las que nacieron directamente en cuentas existentes (venta directa / cross-selling / renovaciones, sin pasar por un Lead). En otras palabras: para ver el panorama completo de oportunidades (incluida venta directa), no se debe mandar `status_lead`.
- **`stage_opp` filtra oportunidades, no prospectos.** Cuando se usa, solo quedan items que tienen una oportunidad en esa etapa; los prospectos sin oportunidad (nuevos, stand by, no convertidos) quedan excluidos del resultado.
- **La paginación (`page`/`size`) es en memoria**, sobre la lista ya filtrada por todos los demás parámetros. Los KPIs (`resumen_ejecutivo`, `detalle_*`) se calculan sobre el **total filtrado**, no sobre la página actual — reflejan siempre el conjunto completo que cumple los filtros, no solo lo que se ve en la página.

---

## 5. Estructura de la respuesta

```json
{
  "status": "success",
  "meta": {
    "numero_asesor": "A123",
    "nombre_asesor": "Juan Pérez",
    "fecha_minima": "2026-01-15T10:00:00+00:00",
    "resumen_ejecutivo": { ... },
    "detalle_prospeccion": { ... },
    "detalle_oportunidades": { ... },
    "detalle_folios_tramite": { ... },
    "pagination": { ... },
    "filtros_aplicados": { ... }
  },
  "items": [ { ... } ]
}
```

### 5.1 `meta`

| Campo | Descripción |
|---|---|
| `numero_asesor` | Eco del parámetro recibido. |
| `nombre_asesor` | Nombre del asesor. Se busca primero como `User` activo (`Alias`); si no existe, como `Asesor_externo__c`. `null` si no se encuentra en ninguno de los dos. |
| `fecha_minima` | Fecha de creación más antigua entre todos los prospectos, oportunidades y folios que quedaron en el resultado filtrado (no solo en la página actual). Sirve para saber desde cuándo hay actividad del asesor dentro del filtro aplicado. `null` si no hay registros. |

#### `resumen_ejecutivo.totales_embudo`

| Campo | Significado |
|---|---|
| `total_prospectos` | Prospectos totales, en cualquier etapa (incluye convertidos). |
| `total_oportunidades` | Total de oportunidades en cualquier etapa. |
| `total_polizas_emitidas` | Folios que llegaron a emisión de póliza (`poliza_emitida = true` en el folio). |
| `total_canceladas` | De las pólizas emitidas, cuántas tienen status de póliza `Cancelado`. |
| `total_vigente` | De las pólizas emitidas, cuántas tienen status de póliza `Vigente`. |

`total_canceladas` + `total_vigente` no necesariamente suman `total_polizas_emitidas`: solo se cuentan si el status de la póliza relacionada es exactamente `Cancelado` o `Vigente`; cualquier otro status (o folio sin póliza vinculada) no se contabiliza en ninguno de los dos.

#### `resumen_ejecutivo.metrica_financiera`

| Campo | Significado |
|---|---|
| `monto_total_cotizado` | Suma de `prima_total_cotizada` (campo de la oportunidad) de todas las oportunidades en el resultado filtrado. |
| `monto_total_emitido` | Suma de `prima_total_emitida` (campo de la oportunidad) de todas las oportunidades en el resultado filtrado. |

`resumen_ejecutivo.total_registros_seguimiento`: cantidad total de items de seguimiento (prospectos + ventas directas) que cumplen el filtro — es el mismo valor que `pagination.total_records`.

#### `detalle_prospeccion`

| Campo | Significado |
|---|---|
| `convertidos` | Prospectos que se volvieron oportunidad y cuenta (`IsConverted = true`). |
| `no_convertidos` | Prospectos que no procedieron (no convertidos y sin status `Nuevo`/`Stand by`). |
| `stand_by` | Prospectos que fueron atendidos pero aún no se definen como convertidos o no convertidos. |
| `nuevos` | Prospectos nuevos, sin atender todavía. |

#### `detalle_oportunidades`

| Campo | Significado |
|---|---|
| `origen.prospectos` | Oportunidades que vienen de un prospecto convertido (Lead → Opportunity). |
| `origen.cuentas_existentes` | Oportunidades que nacieron directamente en una cuenta ya existente en Salesforce, sin pasar por un Lead (venta directa / cross-selling / renovación). |
| `etapas.poliza_emitida` | Oportunidades cuya etapa es "Póliza emitida": llegaron a folio y concluyeron con emisión. |
| `etapas.poliza_no_emitida` | Oportunidades en "Póliza no emitida": no se logró la emisión (pudo haber llegado a folio y no emitirse, o nunca llegar a folio). |
| `etapas.cerrado_ganado` | Oportunidades en "Cerrado ganado": están por terminar, incluso puede que el folio ya esté en proceso. |
| `etapas.cotizacion` | Oportunidades recién en etapa de cotización. |
| `etapas.otros` | Etapas que no están en el catálogo vigente (residuo de versiones anteriores del negocio o etapas inactivas). No incluye "Nueva" ni "Proceso de cierre", que se cuentan pero no tienen su propia llave en este bloque (ver nota abajo). |

> Nota: `etapas` solo expone `poliza_emitida`, `poliza_no_emitida`, `cerrado_ganado`, `cotizacion` y `otros`. Las oportunidades en etapa "Nueva" o "Proceso de cierre" se cuentan internamente pero **no** aparecen desglosadas en este bloque de la respuesta; sí forman parte de `total_oportunidades`.

#### `detalle_folios_tramite`

| Campo | Significado |
|---|---|
| `total_folios` | Folios (Cases) totales creados a partir de una oportunidad. |
| `emitidos` | Folios que concluyeron con emisión de póliza. |
| `en_proceso` | Folios en trámite, que no han concluido ni en emisión ni en no-emisión. |
| `no_emitidos` | Folios que concluyeron sin emitirse. |

#### `pagination`

| Campo | Significado |
|---|---|
| `page` | Página actual (eco del parámetro). |
| `size` | Tamaño de página (eco del parámetro). |
| `total_pages` | Total de páginas disponibles según el filtro aplicado. |
| `total_records` | Total de registros que cumplen el filtro (antes de paginar). |

#### `filtros_aplicados`

Eco de los filtros recibidos en la request (`status_lead`, `stage_opp`, `fecha_inicio`, `fecha_fin`, `periodo`, `con_folio`), útil para que el frontend confirme qué se aplicó realmente.

---

### 5.2 `items[]`

Cada elemento representa un registro de seguimiento (un prospecto, o una oportunidad de venta directa sin prospecto).

| Campo | Descripción |
|---|---|
| `seguimiento_id` | Identificador correlativo dentro de la respuesta (`TRC-001`, `TRC-002`, ...). Solo sirve para referenciar filas dentro del mismo resultado, no es un Id de Salesforce. |
| `origen_registro` | Clasifica el escenario del registro (ver tabla abajo). |
| `prospecto` | Datos del Lead. `null` cuando el registro es venta directa sobre una cuenta existente (no hubo Lead). |
| `cuenta` | Datos de la cuenta (Account). Presente si el Lead se convirtió, o si la oportunidad de venta directa tiene cuenta asociada. `null` en prospectos no convertidos. |
| `oportunidad` | Datos de la oportunidad (Opportunity). `null` si el prospecto no se ha convertido en oportunidad. |
| `folios_emision` | Lista de folios (Cases) de emisión vinculados a la oportunidad. Lista vacía si aún no hay folios. |

**`origen_registro` — valores posibles:**

| Valor | Significado |
|---|---|
| `PROSPECTO_CONVERTIDO` | Escenario A: hay un Lead convertido con oportunidad asociada. |
| `VENTA_DIRECTA_CUENTA` | Escenario B: la oportunidad nació directamente en una cuenta existente, sin Lead de por medio. |
| `PROSPECTO_NO_CONVERTIDO` | Escenario C: Lead sin convertir, sin oportunidad todavía. |

#### `prospecto` (`ProspectoInfo`)

Mapea el Lead de Salesforce. Los campos reflejan directamente atributos del Lead (ver `mapear_prospecto` en `trazabilidad_asesor.py`):

| Campo | Origen (Salesforce) | Notas |
|---|---|---|
| `lead_id` | `Lead.Id` | |
| `name` | `Lead.Name` | |
| `status` | `Lead.Status` | Uno de `Nuevo`, `Stand by`, `Convertido`, `No convertido` (u otro valor libre en Salesforce). |
| `is_converted` | `Lead.IsConverted` | |
| `negocio` | `Lead.Negocio__c` | Línea/unidad de negocio del prospecto. |
| `filial` | `Lead.Filial__c` | |
| `no_expediente_no_colaborador` | `Lead.No_expediente_No_colaborador__c` | Número de expediente o de colaborador asociado. |
| `rfc` | `Lead.RFC__c` | |
| `estado_republica` | `Lead.Estado_de_la_republica__c` | |
| `genero` | `Lead.Genero__c` | |
| `edad` | `Lead.Edad__c` | |
| `fecha_nacimiento` | `Lead.Fecha_de_nacimiento__c` | |
| `ramos_interes` | `Lead.Ramos_de_interes__c` | Ramo(s) de seguro de interés. |
| `email` | `Lead.Email` | |
| `mobile_phone` | `Lead.MobilePhone` | |
| `lead_source` | `Lead.LeadSource` | Canal/fuente de origen del prospecto. |
| `nivel_interes` | `Lead.Nivel_interes__c` | |
| `presupuesto_disponible` | `Lead.Presupuesto_disponible__c` | Numérico; si el valor en Salesforce es un rango de texto (ej. `"$200 – $400"`) se normaliza a `null` porque no es un número único. |
| `campana_del` | `Lead.Campana_del__r.Name` (o `Campana_del__c` si no hay relación) | Campaña de origen. |
| `razon_perdida` | `Lead.Raz_n_de_perdida__c` | Razón por la que se perdió el prospecto. |
| `impedimentos` | `Lead.Impedimentos__c` | |
| `comentarios_lead_perdido` | `Lead.Comentarios_lead_perdido__c` | |
| `owner_name` | `Lead.Owner.Name` | Dueño/asesor asignado en Salesforce. |
| `created_by_name` / `last_modified_by_name` | `Lead.CreatedBy.Name` / `Lead.LastModifiedBy.Name` | |
| `created_date` / `last_modified_date` | `Lead.CreatedDate` / `Lead.LastModifiedDate` | |

#### `cuenta` (`CuentaInfo`)

| Campo | Origen | Notas |
|---|---|---|
| `account_id` | `Account.Id` | |
| `account_name` | `Account.Name` (o el nombre del Lead si la cuenta no trae `Name`) | |
| `created_by_name` | `Account.CreatedBy.Name` | |
| `created_date` | `Account.CreatedDate` | |

#### `oportunidad` (`OportunidadInfo`)

| Campo | Origen (Salesforce) | Notas |
|---|---|---|
| `opportunity_id` | `Opportunity.Id` | |
| `name` | `Opportunity.Name` | |
| `stage_name` | `Opportunity.StageName` | Ver `STAGE_OPP_VALIDOS`. |
| `sub_estatus` | `Opportunity.Sub_estatus__c` | Sub-estado dentro de la etapa. |
| `record_type_name` | `Opportunity.RecordType.Name` | Tipo de registro de la oportunidad. |
| `campaign_name` | `Opportunity.Campaign.Name` | |
| `presupuesto_disponible` | `Opportunity.Presupuesto_disponible__c` | |
| `ramos_interes` | `Opportunity.Ramos_de_interes__c` | |
| `nivel_interes` | `Opportunity.Nivel_interes__c` | |
| `owner_name` | `Opportunity.Owner.Name` | |
| `origen_oportunidad` | `Opportunity.Origen_de_oportunidad__c` | (Campo consultado pero no incluido en `OPPORTUNITY_FIELDS`; puede regresar siempre `null` — ver nota abajo.) |
| `close_date` | `Opportunity.CloseDate` | Fecha estimada/real de cierre. |
| `probability` | `Opportunity.Probability` | |
| `fecha_seguimiento` | `Opportunity.Fecha_de_seguimiento__c` | |
| `fecha_cita_agendada` | `Opportunity.Fecha_de_cita_agendada__c` | |
| `ciclo_de_vida` | `Opportunity.Ciclo_de_vida__c` | |
| `duracion_etapas.nueva_dias` / `.cotizacion_dias` / `.proceso_cierre_dias` | `Duracion_en_etapa_Nueva__c` / `Duracion_en_etapa_Cotizacion__c` / `Duracion_en_etapa_Proceso_de_cierre__c` | Días que la oportunidad ha permanecido en cada etapa. |
| `responsable_decision` | `Opportunity.Responsable_decision__c` | Quién toma la decisión de compra. |
| `tiempo_estimado` | `Opportunity.Tiempo_estimado__c` | Tiempo estimado para el cierre. |
| `impedimentos` | `Opportunity.Impedimentos__c` | |
| `ramos` / `sub_ramos` | `Opportunity.Ramos__c` / `Opportunity.Sub_ramos__c` | |
| `prima_total_cotizada` | `Opportunity.Prima_total_cotizada__c` | Usado para `monto_total_cotizado`. |
| `prima_total_emitida` | `Opportunity.Prima_total_emitida__c` | Usado para `monto_total_emitido`. |
| `cotizacion` | `Opportunity.Cotizacion__c` | Puede venir como texto o booleano según el dato en Salesforce. |
| `razon_perdida` / `otra_razon_perdida` | `Opportunity.Razon_de_perdida__c` / `Otra_razon_de_perdida__c` | |
| `created_date` / `last_modified_date` / `last_modified_by_name` | `Opportunity.CreatedDate` / `LastModifiedDate` / `LastModifiedBy.Name` | |

> Nota: `origen_oportunidad` está en el mapeo (`mapear_oportunidad`) pero el campo `Origen_de_oportunidad__c` no forma parte de `OPPORTUNITY_FIELDS` (el SELECT de la consulta SOQL). En la práctica esto puede devolver siempre `null`; si el frontend necesita este dato, hay que agregar el campo a la consulta en `trazabilidad_asesor.py`.

#### `folios_emision[]` (`FolioEmisionInfo`)

Cada folio es un `Case` de Salesforce vinculado a la oportunidad mediante `Oportunidad__c`:

| Campo | Origen (Salesforce) | Notas |
|---|---|---|
| `case_id` | `Case.Id` | |
| `case_number` | `Case.CaseNumber` | Número de caso visible en Salesforce. |
| `nomenclatura` | `Case.Nomenclatura_campo_bandera__c` | |
| `status` | `Case.Status` | Estado del trámite del caso (workflow del folio, **no** el status de la póliza). |
| `subject` | `Case.Subject` | |
| `tipo_movimiento` | `Case.Tipo_de_movimiento__c` | |
| `poliza_name` | `Case.P_liza_de_seguro__r.Name` (o `P_liza_de_seguro__c` si no hay relación) | |
| `poliza_prima_total` | `Case.P_liza_de_seguro__r.Prima_total_for__c` | Prima total de la póliza vinculada. |
| `poliza_status` | `Case.P_liza_de_seguro__r.Status` | Status de la póliza en sí (ej. `Vigente`, `Cancelado`). Es la base de `total_canceladas`/`total_vigente` en los KPIs. |
| `poliza_emitida` | `Case.Poliza_emitida__c` | Booleano: el folio concluyó con emisión. |
| `poliza_no_emitida` | `Case.Poliza_no_emitida__c` | Booleano: el folio concluyó sin emisión. Si ambos son `false`, el folio se considera "en proceso" en `detalle_folios_tramite.en_proceso`. |
| `razon_no_emision` | `Case.Razon_de_no_emision__c` | |
| `ramo` / `sub_ramos` | `Case.Ramo__c` / `Case.Sub_ramos__c` | |
| `aseguradora` | `Case.Aseguradora__c` | |
| `producto_polizas` | `Case.Producto_polizas__c` | |
| `created_date` / `closed_date` | `Case.CreatedDate` / `Case.ClosedDate` | |
| `asesor_externo_name` | `Case.Asesor_externo__r.Name` | |
| `created_by_name` / `last_modified_by_name` / `owner_name` | `Case.CreatedBy.Name` / `LastModifiedBy.Name` / `Owner.Name` | |

---

## 6. Errores

| Código | Cuándo ocurre |
|---|---|
| `400` | `numero_asesor` vacío, o `status_lead` / `stage_opp` con un valor fuera del catálogo permitido. |
| `401` | Credenciales de Basic Auth ausentes o incorrectas. |
| `500` | Error inesperado del servidor (incluye fallas de conexión con Salesforce no relacionadas con expiración de sesión, que se reintenta automáticamente de forma transparente). |

---

## 7. Ejemplo

```
GET /api/v1/seguimiento/asesor?numero_asesor=A123&fecha_inicio=2026-07-01&page=0&size=10
Authorization: Basic <credenciales>
```

Respuesta (resumida):

```json
{
  "status": "success",
  "meta": {
    "numero_asesor": "A123",
    "nombre_asesor": "Juan Pérez",
    "fecha_minima": "2026-07-02T14:00:00+00:00",
    "resumen_ejecutivo": {
      "totales_embudo": {
        "total_prospectos": 92,
        "total_oportunidades": 71,
        "total_polizas_emitidas": 10,
        "total_canceladas": 1,
        "total_vigente": 9
      },
      "metrica_financiera": {
        "monto_total_cotizado": 0,
        "monto_total_emitido": 108352.54
      },
      "total_registros_seguimiento": 153
    },
    "detalle_prospeccion": { "convertidos": 10, "no_convertidos": 0, "stand_by": 1, "nuevos": 81 },
    "detalle_oportunidades": {
      "origen": { "prospectos": 10, "cuentas_existentes": 61 },
      "etapas": { "poliza_emitida": 10, "poliza_no_emitida": 18, "cerrado_ganado": 5, "cotizacion": 23, "otros": 0 }
    },
    "detalle_folios_tramite": { "total_folios": 16, "emitidos": 10, "en_proceso": 5, "no_emitidos": 1 },
    "pagination": { "page": 0, "size": 10, "total_pages": 16, "total_records": 153 },
    "filtros_aplicados": { "status_lead": null, "stage_opp": null, "fecha_inicio": "2026-07-01", "fecha_fin": null, "periodo": null, "con_folio": null }
  },
  "items": [ ]
}
```
