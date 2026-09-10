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
| `ramo` | string | No | `VIDA`, `DAÑOS`, `ACCIDENTES Y ENFERMEDADES` | Filtra items donde el prospecto (`Ramos_de_interes__c`), la oportunidad (`Ramos_de_interes__c`) o algún folio (`Ramo__c`) coincida con el ramo pedido. Un solo valor (no admite lista separada por coma en este endpoint). |
| `fecha_inicio` | string (`YYYY-MM-DD`) | No | — | Filtra registros con `CreatedDate >=` esta fecha. Se aplica en la consulta a Salesforce sobre Leads y Oportunidades (no sobre folios). |
| `fecha_fin` | string (`YYYY-MM-DD`) | No | — | Filtra registros con `CreatedDate <=` esta fecha. Misma lógica que `fecha_inicio`. |
| `periodo` | string | No | `YYYY-MM` o `YYYY-MM:YYYY-MM` (rango) | Filtro alterno de fecha, aplicado **después** de traer los datos. Incluye un registro si el Lead, la Oportunidad **o alguna Póliza/Folio** fue creado dentro del periodo. Es independiente de `fecha_inicio`/`fecha_fin` — puedes usar uno u otro según si necesitas rango exacto (`fecha_inicio`/`fecha_fin`) o mes calendario con cobertura de folios (`periodo`). |
| `con_folio` | boolean | No | `true` / `false` | Si `true`, solo regresa items que ya tienen al menos un folio de emisión. Si `false`, solo items sin folios. Se aplica al final, después de todos los demás filtros. |
| `page` | int | No | `>= 0` (por defecto `0`) | Índice de página, base cero. |
| `size` | int | No | `1` a `100` (por defecto `10`) | Cantidad de registros por página. |

Valores inválidos en `status_lead`, `stage_opp` o `ramo` devuelven `400 Bad Request` con el detalle de los valores permitidos.

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
    "detalle_ramos": { ... },
    "produccion_periodo_cierre": { ... },
    "gestion_cohorte_creacion": { ... },
    "eficiencia_prospeccion": { ... },
    "eficiencia_comercial": { ... },
    "metrica_financiera_cohorte": { ... },
    "distribucion_origen": [ { ... } ],
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

#### `detalle_ramos`

Desglose de prospectos, oportunidades y folios por ramo (`VIDA`, `DAÑOS`, `ACCIDENTES Y ENFERMEDADES`; los folios además por sub-ramo). Como no existen valores fuera de estos catálogos, lo que cae en `sin_ramo`/`sin_sub_ramo` es un campo vacío/no capturado — sirve para medir qué tan bien se está trazando el dato, no solo para agrupar.

| Campo | Significado |
|---|---|
| `prospectos.<RAMO>` / `.sin_ramo` | Prospectos por `Ramos_de_interes__c` del Lead. |
| `oportunidades.<RAMO>` / `.sin_ramo` | Oportunidades por `Ramos_de_interes__c` de la Opportunity. |
| `folios.ramo.<RAMO>` / `.sin_ramo` | Folios por `Ramo__c` del Case. |
| `folios.sub_ramo.<SUB_RAMO>` / `.sin_sub_ramo` | Folios por `Sub_ramos__c` del Case (`GASTOS MÉDICOS MAYORES`, `VIDA INDIVIDUAL`, `VIDA GRUPO`, `HOGAR`, `AUTOMÓVILES`). |

#### `produccion_periodo_cierre`

**Producción real del periodo**: folios **emitidos** cuyo `Case.ClosedDate` cae en el rango consultado, sin importar cuándo se creó la oportunidad que los originó — incluye "arrastre" (negociaciones de meses anteriores que cerraron ahora). Es `null` si no se pudo resolver el `User` de Salesforce del asesor (requiere una consulta adicional propia; ver nota más abajo).

| Campo | Significado |
|---|---|
| `polizas_emitidas_total` | Folios emitidos cuyo `ClosedDate` cae en el rango. |
| `prima_colocada_total` | Suma de la prima de esos folios. |
| `dias_promedio_emision` | Promedio de días entre el origen (creación del Lead si viene de prospecto, o de la Opportunity si es venta directa) y el `ClosedDate` del folio. `null` si no hay folios emitidos. |
| `total_canceladas` / `total_vigentes` | De esos folios emitidos, cuántas pólizas están en status `Cancelado` / `Vigente`. |
| `ticket_promedio_prima` | Prima promedio por cada póliza emitida en la producción del periodo (`prima_colocada_total / polizas_emitidas_total`). |
| `composicion_origen_emisiones.prospectos_nuevos` / `.cuentas_existentes` | De los folios emitidos del periodo, cuántos vienen de un Lead convertido vs. de una cuenta existente (venta directa). |
| `composicion_origen_emisiones.pct_origen_prospectos` | Porcentaje de pólizas emitidas del periodo que vinieron de prospectos nuevos. |
| `composicion_origen_emisiones.pct_origen_cuentas_existentes` | Porcentaje de pólizas emitidas del periodo que vinieron de cuentas existentes. |
| `composicion_inmediatez_emisiones.mismo_periodo` / `.arrastre_pasado` | De los folios emitidos del periodo, cuántos vienen de una oportunidad **creada en ese mismo rango** vs. de una oportunidad de un periodo anterior (arrastre). |
| `composicion_inmediatez_emisiones.pct_mismo_periodo` | Porcentaje de emisiones del periodo negociadas en este mismo mes. |
| `composicion_inmediatez_emisiones.pct_arrastre_pasado` | Porcentaje de emisiones del periodo negociadas en meses pasados. |
| `distribucion_ramo_emisiones` | Desglose de la prima emitida del periodo por ramo, con su composición interna (sub_ramo/producto y, en ACCIDENTES Y ENFERMEDADES, empresa) y su partición por inmediatez (mismo periodo vs. arrastre). Ver el shape completo (`MetricasBucketEmision`) más abajo. |

> Nota: a diferencia de `resumen_ejecutivo`/`detalle_*`, este bloque **no** aplica los filtros `status_lead`/`stage_opp`/`ramo`/`con_folio` — refleja toda la producción cerrada del asesor en el rango de fechas, porque requiere una consulta adicional sin acotar por `CreatedDate` (para no perder el arrastre).

##### Shape común de cada bucket (`MetricasBucketEmision`)

`distribucion_ramo_emisiones[]` y sus dos desgloses anidados (`distribucion_sub_ramo[]`, `distribucion_empresa[]`) comparten exactamente el mismo set de métricas — solo cambia el campo que identifica el bucket (`ramo`, `sub_ramo` o `empresa`):

| Campo | Significado |
|---|---|
| `monto` / `prima_total` | Prima total del bucket (son el mismo valor; `prima_total` está para que quede junto a `prima_mismo_periodo`/`prima_arrastre_pasado` y no haya que buscarlo arriba). |
| `porcentaje` | `monto` como % — ver la base de comparación abajo, cambia entre nivel ramo y desgloses anidados. |
| `emitidas` | Cantidad de pólizas (folios) emitidas que caen en este bucket. |
| `porcentaje_emitidas` | `emitidas` como % — misma base que `porcentaje`, pero contando pólizas en vez de sumar prima (puede diferir de `porcentaje` si el bucket tiene pocas pólizas de ticket alto, o muchas de ticket bajo). |
| `emitidas_mismo_periodo` / `emitidas_arrastre_pasado` | De `emitidas`, cuántas vienen de una oportunidad creada en el rango consultado vs. de una oportunidad de un periodo anterior (arrastre) — mismo criterio que `composicion_inmediatez_emisiones` a nivel de todo el asesor. |
| `prima_mismo_periodo` / `prima_arrastre_pasado` | Prima de esas mismas pólizas, partida por el mismo criterio. `prima_mismo_periodo + prima_arrastre_pasado = prima_total`. |

**Base de los porcentajes** — igual que antes, cada nivel calcula `porcentaje`/`porcentaje_emitidas` contra una base distinta, para que sumen 100% entre los hermanos de ese nivel:

| Nivel | Base de `porcentaje` | Base de `porcentaje_emitidas` |
|---|---|---|
| `distribucion_ramo_emisiones[]` (ramo) | `prima_colocada_total` (todo el asesor) | `polizas_emitidas_total` (todo el asesor) |
| `distribucion_sub_ramo[]` / `distribucion_empresa[]` (anidados) | `monto` del ramo padre | `emitidas` del ramo padre |

##### `distribucion_ramo_emisiones[].distribucion_sub_ramo`

Desglose granular dentro de cada ramo, de las mismas pólizas ya contadas en `distribucion_ramo_emisiones`. La fuente del campo cambia según el ramo:

| Ramo | Campo fuente | Ejemplo de valores |
|---|---|---|
| `VIDA` | `Case.Producto_polizas__c` (**no** `Sub_ramos__c`) | `VIDAMAS`, `VIDA INDIVIDUAL`, ... |
| `DAÑOS`, `ACCIDENTES Y ENFERMEDADES` | `Case.Sub_ramos__c` | `HOGAR`, `AUTOMÓVILES`, `GASTOS MÉDICOS MAYORES`, ... |

Un folio sin ese campo capturado en Salesforce se agrupa bajo `sub_ramo: "SIN_SUB_RAMO"`.

##### `distribucion_ramo_emisiones[].distribucion_empresa`

Solo se calcula (y solo trae datos) dentro del ramo `ACCIDENTES Y ENFERMEDADES`; en `VIDA` y `DAÑOS` siempre viene como lista vacía `[]`. Desglosa la prima del ramo por la empresa dueña de la cuenta (`Account.Negocio__c` de la cuenta del item — convertida desde el Lead, o la cuenta directa de la oportunidad en venta directa). `empresa` es `"GRUPO BIMBO, S.A.B. DE C.V."`, `"SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA"`, o `"OTROS"` si `Account.Negocio__c` no coincide con ninguna de esas dos (incluye cuentas sin ese campo capturado).

#### `gestion_cohorte_creacion`

Seguimiento operativo del volumen creado en el periodo: Leads/Oportunidades cuyo propio `CreatedDate` cae en el rango, y qué tan bien les fue.

| Campo | Significado |
|---|---|
| `leads_registrados` | Prospectos creados en el rango (mismo valor que `total_prospectos` cuando no hay otros filtros). |
| `oportunidades_generadas` | Oportunidades creadas en el rango (vengan o no de un Lead). |
| `emisiones_mismo_periodo` | De esas oportunidades, cuántas ya tienen un folio emitido **cuyo `ClosedDate` también cae en el rango**. Si la oportunidad se creó en el rango pero su folio cerró después, sigue "en proceso" al momento de esta consulta. |
| `oportunidades_en_proceso` | Oportunidades del cohorte que no tienen folio emitido ni marcado como no emitido todavía. |
| `oportunidades_no_emitidas` | Oportunidades del cohorte marcadas como no emitidas (por `StageName = "Póliza no emitida"` o por el folio; algunas de estas oportunidades nunca llegan a tener un `Case` asociado). |

#### `eficiencia_prospeccion` (Eje A — sobre `leads_registrados`)

| Campo | Significado |
|---|---|
| `tasa_conversion_prospecto_pct` | Porcentaje de leads registrados que fueron convertidos a Cuenta/Oportunidad. |
| `tasa_cierre_prospeccion_pct` | Porcentaje de leads registrados que llegaron hasta póliza emitida. |

#### `eficiencia_comercial` (Eje B — sobre `oportunidades_generadas`)

No mide oportunidades contra leads: la mayoría de las oportunidades nacen de cuentas existentes, no de un Lead, así que esa relación distorsionaría la lectura comercial.

| Campo | Significado |
|---|---|
| `tasa_cierre_oportunidad_pct` | Porcentaje de éxito/cierre sobre todas las oportunidades creadas en el periodo. |
| `tasa_oportunidades_perdidas_pct` | Porcentaje de oportunidades creadas en el periodo que se marcaron como no emitidas. |
| `pct_origen_cuentas_existentes` | Porcentaje de las oportunidades del periodo que provinieron de la cartera/cuentas existentes. |
| `pct_origen_prospectos` | Porcentaje de las oportunidades del periodo que provinieron de la prospección nueva. |

#### `metrica_financiera_cohorte`

| Campo | Significado |
|---|---|
| `monto_total_cotizado` | Suma de `prima_total_cotizada` de las oportunidades del resultado filtrado (mismo criterio que `resumen_ejecutivo.metrica_financiera.monto_total_cotizado`, expuesto aquí junto al resto de los bloques de cohorte/eficiencia). |

#### `distribucion_origen`

Desglose por canal de origen (`Origen_de_oportunidad__c` de la oportunidad, o `LeadSource` del prospecto si no hay oportunidad) de los registros del cohorte — `"Sin identificar"` agrupa los que no traen ese dato.

| Campo | Significado |
|---|---|
| `origen` | Nombre del canal (`Sitio web`, `WhatsApp`, `Llamada Entrante`, etc.), o `"Sin identificar"`. |
| `total` | Cuántos registros del cohorte tienen ese origen. |
| `porcentaje` | `total` como porcentaje de todos los registros con origen resuelto. |
| `emitidas` | De esos, cuántos ya tienen un folio emitido en el mismo periodo (mismo criterio que `gestion_cohorte_creacion.emisiones_mismo_periodo`). |
| `porcentaje_emitidas` | `emitidas` como porcentaje de `total` **dentro de ese mismo origen** (no contra el total general). |

#### `pagination`

| Campo | Significado |
|---|---|
| `page` | Página actual (eco del parámetro). |
| `size` | Tamaño de página (eco del parámetro). |
| `total_pages` | Total de páginas disponibles según el filtro aplicado. |
| `total_records` | Total de registros que cumplen el filtro (antes de paginar). |

#### `filtros_aplicados`

Eco de los filtros recibidos en la request (`status_lead`, `stage_opp`, `ramo`, `fecha_inicio`, `fecha_fin`, `periodo`, `con_folio`), útil para que el frontend confirme qué se aplicó realmente.

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
| `negocio` | `Account.Negocio__c` | Empresa/línea de negocio de la cuenta. Es la base de `distribucion_ramo_emisiones[].distribucion_empresa` (ver sección de `produccion_periodo_cierre`). |
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
| `origen_oportunidad` | `Opportunity.Origen_de_oportunidad__c` | Canal/origen de la oportunidad; base de `distribucion_origen`. |
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
| `producto_polizas` | `Case.Producto_polizas__c` | Producto contratado. En folios de ramo `VIDA`, es el campo que alimenta `distribucion_ramo_emisiones[].distribucion_sub_ramo` (en vez de `sub_ramos`, que en VIDA no es útil para el negocio). |
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
    "detalle_ramos": {
      "prospectos": { "VIDA": 2, "DAÑOS": 5, "ACCIDENTES Y ENFERMEDADES": 3, "sin_ramo": 82 },
      "oportunidades": { "VIDA": 1, "DAÑOS": 4, "ACCIDENTES Y ENFERMEDADES": 2, "sin_ramo": 64 },
      "folios": {
        "ramo": { "VIDA": 0, "DAÑOS": 8, "ACCIDENTES Y ENFERMEDADES": 2, "sin_ramo": 0 },
        "sub_ramo": { "GASTOS MÉDICOS MAYORES": 2, "VIDA INDIVIDUAL": 0, "VIDA GRUPO": 0, "HOGAR": 0, "AUTOMÓVILES": 8, "sin_sub_ramo": 0 }
      }
    },
    "produccion_periodo_cierre": {
      "polizas_emitidas_total": 33,
      "prima_colocada_total": 522828.12,
      "dias_promedio_emision": 33.9,
      "total_canceladas": 0,
      "total_vigentes": 33,
      "ticket_promedio_prima": 15843.28,
      "composicion_origen_emisiones": { "prospectos_nuevos": 2, "cuentas_existentes": 31, "pct_origen_prospectos": 6.06, "pct_origen_cuentas_existentes": 93.94 },
      "composicion_inmediatez_emisiones": { "mismo_periodo": 20, "arrastre_pasado": 13, "pct_mismo_periodo": 60.61, "pct_arrastre_pasado": 39.39 },
      "distribucion_ramo_emisiones": [
        {
          "ramo": "DAÑOS",
          "monto": 421004.0,
          "porcentaje": 80.53,
          "emitidas": 27,
          "porcentaje_emitidas": 81.82,
          "emitidas_mismo_periodo": 18,
          "emitidas_arrastre_pasado": 9,
          "prima_mismo_periodo": 280000.0,
          "prima_arrastre_pasado": 141004.0,
          "prima_total": 421004.0,
          "distribucion_sub_ramo": [
            {
              "sub_ramo": "AUTOMÓVILES",
              "monto": 380000.0,
              "porcentaje": 90.26,
              "emitidas": 24,
              "porcentaje_emitidas": 88.89,
              "emitidas_mismo_periodo": 16,
              "emitidas_arrastre_pasado": 8,
              "prima_mismo_periodo": 250000.0,
              "prima_arrastre_pasado": 130000.0,
              "prima_total": 380000.0
            },
            {
              "sub_ramo": "HOGAR",
              "monto": 41004.0,
              "porcentaje": 9.74,
              "emitidas": 3,
              "porcentaje_emitidas": 11.11,
              "emitidas_mismo_periodo": 2,
              "emitidas_arrastre_pasado": 1,
              "prima_mismo_periodo": 30000.0,
              "prima_arrastre_pasado": 11004.0,
              "prima_total": 41004.0
            }
          ],
          "distribucion_empresa": []
        },
        {
          "ramo": "ACCIDENTES Y ENFERMEDADES",
          "monto": 101824.12,
          "porcentaje": 19.47,
          "emitidas": 6,
          "porcentaje_emitidas": 18.18,
          "emitidas_mismo_periodo": 4,
          "emitidas_arrastre_pasado": 2,
          "prima_mismo_periodo": 75000.0,
          "prima_arrastre_pasado": 26824.12,
          "prima_total": 101824.12,
          "distribucion_sub_ramo": [
            {
              "sub_ramo": "GASTOS MÉDICOS MAYORES",
              "monto": 101824.12,
              "porcentaje": 100.0,
              "emitidas": 6,
              "porcentaje_emitidas": 100.0,
              "emitidas_mismo_periodo": 4,
              "emitidas_arrastre_pasado": 2,
              "prima_mismo_periodo": 75000.0,
              "prima_arrastre_pasado": 26824.12,
              "prima_total": 101824.12
            }
          ],
          "distribucion_empresa": [
            {
              "empresa": "GRUPO BIMBO, S.A.B. DE C.V.",
              "monto": 70000.0,
              "porcentaje": 68.74,
              "emitidas": 4,
              "porcentaje_emitidas": 66.67,
              "emitidas_mismo_periodo": 3,
              "emitidas_arrastre_pasado": 1,
              "prima_mismo_periodo": 55000.0,
              "prima_arrastre_pasado": 15000.0,
              "prima_total": 70000.0
            },
            {
              "empresa": "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA",
              "monto": 20000.0,
              "porcentaje": 19.64,
              "emitidas": 1,
              "porcentaje_emitidas": 16.67,
              "emitidas_mismo_periodo": 1,
              "emitidas_arrastre_pasado": 0,
              "prima_mismo_periodo": 20000.0,
              "prima_arrastre_pasado": 0.0,
              "prima_total": 20000.0
            },
            {
              "empresa": "OTROS",
              "monto": 11824.12,
              "porcentaje": 11.61,
              "emitidas": 1,
              "porcentaje_emitidas": 16.67,
              "emitidas_mismo_periodo": 0,
              "emitidas_arrastre_pasado": 1,
              "prima_mismo_periodo": 0.0,
              "prima_arrastre_pasado": 11824.12,
              "prima_total": 11824.12
            }
          ]
        },
        {
          "ramo": "VIDA",
          "monto": 0.0,
          "porcentaje": 0.0,
          "emitidas": 0,
          "porcentaje_emitidas": 0.0,
          "emitidas_mismo_periodo": 0,
          "emitidas_arrastre_pasado": 0,
          "prima_mismo_periodo": 0.0,
          "prima_arrastre_pasado": 0.0,
          "prima_total": 0.0,
          "distribucion_sub_ramo": [],
          "distribucion_empresa": []
        }
      ]
    },
    "gestion_cohorte_creacion": { "leads_registrados": 92, "oportunidades_generadas": 71, "emisiones_mismo_periodo": 20, "oportunidades_en_proceso": 33, "oportunidades_no_emitidas": 18 },
    "eficiencia_prospeccion": { "tasa_conversion_prospecto_pct": 10.87, "tasa_cierre_prospeccion_pct": 2.17 },
    "eficiencia_comercial": { "tasa_cierre_oportunidad_pct": 28.17, "tasa_oportunidades_perdidas_pct": 25.35, "pct_origen_cuentas_existentes": 85.92, "pct_origen_prospectos": 14.08 },
    "metrica_financiera_cohorte": { "monto_total_cotizado": 539072.39 },
    "distribucion_origen": [
      { "origen": "Sitio web", "total": 41, "porcentaje": 44.57, "emitidas": 15, "porcentaje_emitidas": 36.59 },
      { "origen": "Llamada Entrante", "total": 28, "porcentaje": 30.43, "emitidas": 3, "porcentaje_emitidas": 10.71 }
    ],
    "pagination": { "page": 0, "size": 10, "total_pages": 16, "total_records": 153 },
    "filtros_aplicados": { "status_lead": null, "stage_opp": null, "ramo": null, "fecha_inicio": "2026-07-01", "fecha_fin": null, "periodo": null, "con_folio": null }
  },
  "items": [ ]
}
```
