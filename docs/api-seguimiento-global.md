# API de Ranking Global de Asesores — `GET /api/v1/seguimiento/global`

Documentación de consumo para frontend. Endpoint de **solo lectura** (no crea ni modifica nada en Salesforce) que devuelve un leaderboard de **todos los asesores activos** de la empresa, ordenable por distintas métricas comerciales, junto con un resumen agregado de la empresa.

Código fuente: [`app/api/endpoints/seguimiento.py`](../app/api/endpoints/seguimiento.py), lógica en [`app/services/ranking_asesores.py`](../app/services/ranking_asesores.py), modelos de respuesta en [`app/models/schemas.py`](../app/models/schemas.py). Ver también la [documentación del endpoint por-asesor](./api-seguimiento-asesor.md), con el que este endpoint comparte varios de sus bloques de métricas.

---

## 1. Autenticación

El endpoint requiere **HTTP Basic Auth** (`app/dependencias/security.py`). Hay que enviar el header `Authorization: Basic <base64(usuario:password)>` en cada request. Si las credenciales son incorrectas o faltan, responde `401 Unauthorized`.

---

## 2. Endpoint

```
GET /api/v1/seguimiento/global
```

---

## 3. Cómo se arma el roster de asesores

El ranking incluye a **todos los asesores activos**, sin necesidad de pedirlos por número:

1. Se parte de los `User` **activos** de Salesforce con `Alias` definido (`Asesor_externo__c` no tiene ningún campo de estatus/activo propio — la única señal real de actividad es `User.IsActive`).
2. Cada `User` se enriquece con nombre, zona (`Zona__c`) y puesto (`Puesto__c`) desde `Asesor_externo__c`, cruzando por `Numero_de_asesor__c = Alias`.
3. Un `User` activo sin `Asesor_externo__c` correspondiente no entra al roster (no es un asesor de venta). Un `Asesor_externo__c` sin `User` activo (asesor dado de baja) tampoco aparece.

---

## 4. Parámetros de consulta (query params)

| Parámetro | Tipo | Obligatorio | Valores válidos | Descripción |
|---|---|---|---|---|
| `sort_by` | string | No (default `prima_colocada`) | `prima_colocada`, `polizas_emitidas`, `tasa_conversion`, `dias_promedio_emision`, `leads_registrados`, `oportunidades_generadas`, `general` | Criterio de orden del leaderboard. `general` es un promedio de la posición (rank) del asesor en las otras 6 métricas — no un promedio de valores crudos, que mezclarían escalas incompatibles (dinero, días, porcentajes, conteos). Para `dias_promedio_emision`, menor es mejor; para las demás, mayor es mejor. Un asesor sin dato en una métrica recibe la peor posición posible en ella. |
| `order` | string | No (default `DESC`) | `DESC`, `ASC` | Dirección del orden. No aplica a `sort_by=general` (siempre ordena de mejor a peor). |
| `periodo` | string | No | `mensual`, `trimestral`, `anual`, `historico_total` | Ventana **móvil** desde "ahora": `mensual` = últimos 30 días, `trimestral` = últimos 90, `anual` = últimos 365. `historico_total` no acota fechas. Solo se usa si **no** se mandan `fecha_inicio`/`fecha_fin`. |
| `fecha_inicio` | string (`YYYY-MM-DD`) | No | — | Si se manda (junto con o sin `fecha_fin`), tiene **prioridad total** sobre `periodo`. |
| `fecha_fin` | string (`YYYY-MM-DD`) | No | — | Igual que `fecha_inicio`. |
| `ramo` | string | No | `VIDA`, `DAÑOS`, `ACCIDENTES Y ENFERMEDADES` (uno o varios, separados por coma) | Filtra los items de cada asesor a solo los que coincidan con alguno de los ramos pedidos (prospecto, oportunidad o folio), **antes** de calcular sus métricas. Recalcula todo el ranking y el resumen de empresa solo sobre ese ramo. Ej.: `ramo=DAÑOS,VIDA`. |
| `puesto` | string | No | Libre (no hay catálogo fijo — es el valor de `Asesor_externo__c.Puesto__c`) | Filtra el **roster** a solo los asesores con alguno de los puestos pedidos, uno o varios separados por coma, antes de consultar Salesforce (no se traen datos de los asesores excluidos). Ej.: `puesto=Asesor,Telemarketing`. |
| `page` | int | No (default `0`) | `>= 0` | Índice de página del leaderboard, base cero. |
| `size` | int | No (default `20`) | `1` a `100` | Cantidad de asesores por página. |

Valores inválidos en `sort_by`, `order`, `periodo` o `ramo` devuelven `400 Bad Request` con el detalle de los valores permitidos. `puesto` no se valida contra un catálogo (es texto libre tomado de Salesforce).

---

## 5. Comportamiento importante

- **La paginación es solo sobre el leaderboard (`items`)**. `resumen_general_empresa` siempre refleja el total de asesores que cumplen los filtros (`ramo`/`puesto`/fechas), sin importar qué página se esté pidiendo.
- **`ramo` filtra items dentro de cada asesor; `puesto` filtra qué asesores entran al ranking.** Son dos mecanismos distintos: `ramo` recalcula las métricas de cada asesor solo con su negocio de ese ramo; `puesto` decide qué asesores se consideran en absoluto.
- **`items[]` es un leaderboard plano.** Solo trae lo necesario para ordenar/mostrar la tabla (`posicion_ranking`, `vendedor`, `metricas_operativas`). El detalle analítico completo de un asesor (desglose por ramo, origen, producción vs. cohorte) se consulta aparte con `GET /api/v1/seguimiento/asesor?numero_asesor=...` cuando el usuario da clic en una fila — así se evita mandar la "sábana" completa de los 30+ asesores en cada respuesta.
- **Distinción producción vs. cohorte**: igual que en el endpoint por-asesor, `produccion_periodo_cierre` mide lo **cerrado/emitido** en el rango (incluye arrastre de negociaciones viejas), y `gestion_cohorte_creacion` mide lo **creado** en el rango y qué tan bien le fue. Ver el detalle de cada campo en la [documentación del endpoint por-asesor](./api-seguimiento-asesor.md#produccion_periodo_cierre), donde tienen el mismo significado — aquí, a nivel empresa.

---

## 6. Estructura de la respuesta

```json
{
  "status": "success",
  "meta": {
    "fecha_generacion": "2026-09-01T21:34:11Z",
    "resumen_general_empresa": { ... },
    "pagination": { ... },
    "filtros_aplicados": { ... }
  },
  "items": [ { ... } ]
}
```

### 6.1 `meta.fecha_generacion`

Timestamp UTC de cuándo se generó la respuesta (no es una fecha de negocio, es solo para saber qué tan reciente es el snapshot).

### 6.2 `meta.resumen_general_empresa`

Agrega los totales de la empresa sobre **todos** los asesores que cumplen los filtros (antes de paginar).

#### `totales_operativos`

| Campo | Significado |
|---|---|
| `total_asesores_evaluados` | Cuántos asesores entraron al cálculo (después de aplicar `puesto` si se mandó). |
| `leads_registrados` | Suma de leads creados en el rango, de todos los asesores. |
| `cotizaciones_generadas` | Suma de oportunidades cuyo `StageName` actual es "Cotización". |
| `polizas_emitidas` | Suma de `produccion_periodo_cierre.polizas_emitidas_total` de todos los asesores. |
| `prima_colocada_total` | Suma de la prima de esas pólizas emitidas. |

#### `eficiencia_global`

| Campo | Significado |
|---|---|
| `tasa_conversion_global_pct` | % de leads registrados (de toda la empresa) que fueron convertidos. |
| `dias_promedio_emision_global` | Promedio de días de emisión, ponderado por folio (no un promedio simple de los promedios por asesor). `null` si no hay folios emitidos. |
| `distribucion_origen` | Igual que en el endpoint por-asesor, pero sumado entre todos los asesores: desglose por canal de origen (`Sitio web`, `WhatsApp`, etc.) con `total`, `porcentaje`, `emitidas` y `porcentaje_emitidas` (este último, dentro de ese mismo origen). |
| `distribucion_puesto` | Desglose por `Puesto__c` del asesor (ver tabla abajo). |

**`distribucion_puesto[]`** — agrupa **asesores** (no items) por su puesto:

| Campo | Significado |
|---|---|
| `puesto` | Valor de `Puesto__c`, o `"Sin puesto"` si no está capturado. |
| `total` | Suma de `oportunidades_generadas` (cohorte) de los asesores de ese puesto. |
| `porcentaje` | `total` como % de la suma de `total` de todos los puestos. |
| `emitidas` | Total **real** emitido en el rango por los asesores de ese puesto (`emitidas_mismo_periodo + emitidas_arrastre_pasado` — de producción, no de cohorte). |
| `porcentaje_emitidas` | `emitidas` como % del total emitido de **toda la empresa** (no contra `total` de este puesto — `total` es cohorte y `emitidas` es producción, son poblaciones distintas; dividir una entre la otra puede dar más de 100%). |
| `emitidas_mismo_periodo` | De `emitidas`, cuántas vienen de una oportunidad creada en el mismo rango. |
| `emitidas_arrastre_pasado` | De `emitidas`, cuántas vienen de una oportunidad de un periodo anterior (arrastre). |

#### `produccion_periodo_cierre`

Mismos campos y significado que en el [endpoint por-asesor](./api-seguimiento-asesor.md), pero sumados entre todos los asesores del filtro: `polizas_emitidas_total`, `prima_colocada_total`, `dias_promedio_emision`, `total_canceladas`, `total_vigentes`, `ticket_promedio_prima`, `composicion_origen_emisiones` (`pct_origen_prospectos`/`pct_origen_cuentas_existentes` = % de pólizas emitidas del periodo que vinieron de prospectos nuevos / de cuentas existentes), `composicion_inmediatez_emisiones` (`pct_mismo_periodo`/`pct_arrastre_pasado` = % de emisiones del periodo negociadas en este mismo mes / en meses pasados), y `distribucion_ramo_emisiones` (desglose de la prima emitida por ramo, con su composición interna por sub_ramo/producto y, en ACCIDENTES Y ENFERMEDADES, por empresa — cada bucket trae monto y conteo de pólizas, partidos por mismo periodo/arrastre; ver el shape completo `MetricasBucketEmision` y la fuente de campo por ramo en el endpoint por-asesor).

`distribucion_ramo_emisiones` (y sus desgloses anidados) se re-agrega sumando los valores crudos de cada asesor (montos y conteos, tanto totales como partidos por mismo_periodo/arrastre_pasado) y recalculando los porcentajes sobre esa suma — nunca promediando los porcentajes ya redondeados de cada asesor.

#### `gestion_cohorte_creacion`

Seguimiento operativo del volumen creado en el periodo, sumado entre todos los asesores: `leads_registrados`, `oportunidades_generadas`, `emisiones_mismo_periodo`, `oportunidades_en_proceso`, `oportunidades_no_emitidas`. Mismo significado que en el endpoint por-asesor.

#### `eficiencia_prospeccion` (Eje A)

| Campo | Significado |
|---|---|
| `tasa_conversion_prospecto_pct` | Porcentaje de leads registrados que fueron convertidos a Cuenta/Oportunidad. |
| `tasa_cierre_prospeccion_pct` | Porcentaje de leads registrados que llegaron hasta póliza emitida. |

#### `eficiencia_comercial` (Eje B)

| Campo | Significado |
|---|---|
| `tasa_cierre_oportunidad_pct` | Porcentaje de éxito/cierre sobre todas las oportunidades creadas en el periodo. |
| `tasa_oportunidades_perdidas_pct` | Porcentaje de oportunidades creadas en el periodo que se marcaron como no emitidas. |
| `pct_origen_cuentas_existentes` | Porcentaje de las oportunidades del periodo que provinieron de la cartera/cuentas existentes. |
| `pct_origen_prospectos` | Porcentaje de las oportunidades del periodo que provinieron de la prospección nueva. |

#### `metrica_financiera`

| Campo | Significado |
|---|---|
| `monto_total_cotizado` | Suma de `prima_total_cotizada` de las oportunidades del cohorte, de todos los asesores. |
| `monto_total_emitido` | Igual a `produccion_periodo_cierre.prima_colocada_total` (la cifra "oficial" de producción). |

### 6.3 `meta.pagination`

| Campo | Significado |
|---|---|
| `page` / `size` | Eco de los parámetros. |
| `total_pages` | Total de páginas del leaderboard según el filtro aplicado. |
| `total_records` | Total de asesores que cumplen el filtro (antes de paginar). |

### 6.4 `meta.filtros_aplicados`

Eco de `sort_by`, `order`, `periodo`, `fecha_inicio`, `fecha_fin`, `ramo` (lista) y `puesto` (lista).

### 6.5 `items[]` — leaderboard

Cada elemento es un asesor, en el orden pedido por `sort_by`/`order`.

| Campo | Significado |
|---|---|
| `posicion_ranking` | Posición en el ranking completo (no se reinicia por página: si `page=1` y `size=20`, empieza en 21). |
| `vendedor.numero_asesor` | Alias del `User` / `Numero_de_asesor__c`. |
| `vendedor.nombre_asesor` | Nombre del asesor. |
| `vendedor.zona` | `Asesor_externo__c.Zona__c`. |
| `vendedor.puesto` | `Asesor_externo__c.Puesto__c`. |
| `metricas_operativas.leads_registrados` | Leads creados en el rango. |
| `metricas_operativas.cotizaciones_generadas` | Oportunidades en etapa "Cotización". |
| `metricas_operativas.oportunidades_generadas` | Oportunidades creadas en el rango. |
| `metricas_operativas.polizas_emitidas` | Folios emitidos con `ClosedDate` en el rango (incluye arrastre). |
| `metricas_operativas.prima_colocada_total` | Prima de esos folios. |
| `metricas_operativas.dias_promedio_emision` | Promedio de días de emisión del asesor. `null` si no tiene folios emitidos. |
| `metricas_operativas.tasa_conversion_prospecto_pct` | % de sus leads que fueron convertidos. |

Para ver el desglose completo de este asesor (por ramo, por origen, producción vs. cohorte), consultar `GET /api/v1/seguimiento/asesor?numero_asesor=<vendedor.numero_asesor>`.

---

## 7. Errores

| Código | Cuándo ocurre |
|---|---|
| `400` | `sort_by`, `order`, `periodo` o `ramo` con un valor fuera del catálogo permitido, o `fecha_inicio`/`fecha_fin` con formato distinto a `YYYY-MM-DD`. |
| `401` | Credenciales de Basic Auth ausentes o incorrectas. |
| `500` | Error inesperado del servidor. |

---

## 8. Ejemplo

```
GET /api/v1/seguimiento/global?sort_by=prima_colocada&order=DESC&periodo=mensual&puesto=Asesor,Telemarketing&page=0&size=20
Authorization: Basic <credenciales>
```

Respuesta (resumida):

```json
{
  "status": "success",
  "meta": {
    "fecha_generacion": "2026-09-01T22:31:14Z",
    "resumen_general_empresa": {
      "totales_operativos": {
        "total_asesores_evaluados": 30,
        "leads_registrados": 416,
        "cotizaciones_generadas": 93,
        "polizas_emitidas": 471,
        "prima_colocada_total": 6701733.33
      },
      "eficiencia_global": {
        "tasa_conversion_global_pct": 15.87,
        "dias_promedio_emision_global": 16.2,
        "distribucion_origen": [
          { "origen": "Sin identificar", "total": 415, "porcentaje": 34.55, "emitidas": 118, "porcentaje_emitidas": 28.43 }
        ],
        "distribucion_puesto": [
          { "puesto": "Asesor", "total": 637, "porcentaje": 75.38, "emitidas": 351, "porcentaje_emitidas": 75.81, "emitidas_mismo_periodo": 223, "emitidas_arrastre_pasado": 128 },
          { "puesto": "Telemarketing", "total": 208, "porcentaje": 24.62, "emitidas": 112, "porcentaje_emitidas": 24.19, "emitidas_mismo_periodo": 73, "emitidas_arrastre_pasado": 39 }
        ]
      },
      "produccion_periodo_cierre": {
        "polizas_emitidas_total": 471,
        "prima_colocada_total": 6701733.33,
        "dias_promedio_emision": 16.2,
        "total_canceladas": 8,
        "total_vigentes": 460,
        "ticket_promedio_prima": 14228.73,
        "composicion_origen_emisiones": { "prospectos_nuevos": 34, "cuentas_existentes": 437, "pct_origen_prospectos": 7.22, "pct_origen_cuentas_existentes": 92.78 },
        "composicion_inmediatez_emisiones": { "mismo_periodo": 301, "arrastre_pasado": 170, "pct_mismo_periodo": 63.91, "pct_arrastre_pasado": 36.09 },
        "distribucion_ramo_emisiones": [
          {
            "ramo": "DAÑOS",
            "monto": 3296192.13,
            "porcentaje": 49.18,
            "emitidas": 300,
            "porcentaje_emitidas": 63.69,
            "emitidas_mismo_periodo": 192,
            "emitidas_arrastre_pasado": 108,
            "prima_mismo_periodo": 2109562.96,
            "prima_arrastre_pasado": 1186629.17,
            "prima_total": 3296192.13,
            "distribucion_sub_ramo": [
              {
                "sub_ramo": "AUTOMÓVILES",
                "monto": 2900000.0,
                "porcentaje": 87.97,
                "emitidas": 264,
                "porcentaje_emitidas": 88.0,
                "emitidas_mismo_periodo": 169,
                "emitidas_arrastre_pasado": 95,
                "prima_mismo_periodo": 1856000.0,
                "prima_arrastre_pasado": 1044000.0,
                "prima_total": 2900000.0
              },
              {
                "sub_ramo": "HOGAR",
                "monto": 396192.13,
                "porcentaje": 12.03,
                "emitidas": 36,
                "porcentaje_emitidas": 12.0,
                "emitidas_mismo_periodo": 23,
                "emitidas_arrastre_pasado": 13,
                "prima_mismo_periodo": 253562.96,
                "prima_arrastre_pasado": 142629.17,
                "prima_total": 396192.13
              }
            ],
            "distribucion_empresa": []
          },
          {
            "ramo": "ACCIDENTES Y ENFERMEDADES",
            "monto": 1786920.2,
            "porcentaje": 26.66,
            "emitidas": 120,
            "porcentaje_emitidas": 25.48,
            "emitidas_mismo_periodo": 80,
            "emitidas_arrastre_pasado": 40,
            "prima_mismo_periodo": 1200000.0,
            "prima_arrastre_pasado": 586920.2,
            "prima_total": 1786920.2,
            "distribucion_sub_ramo": [
              {
                "sub_ramo": "GASTOS MÉDICOS MAYORES",
                "monto": 1786920.2,
                "porcentaje": 100.0,
                "emitidas": 120,
                "porcentaje_emitidas": 100.0,
                "emitidas_mismo_periodo": 80,
                "emitidas_arrastre_pasado": 40,
                "prima_mismo_periodo": 1200000.0,
                "prima_arrastre_pasado": 586920.2,
                "prima_total": 1786920.2
              }
            ],
            "distribucion_empresa": [
              {
                "empresa": "GRUPO BIMBO, S.A.B. DE C.V.",
                "monto": 900000.0,
                "porcentaje": 50.37,
                "emitidas": 60,
                "porcentaje_emitidas": 50.0,
                "emitidas_mismo_periodo": 40,
                "emitidas_arrastre_pasado": 20,
                "prima_mismo_periodo": 600000.0,
                "prima_arrastre_pasado": 300000.0,
                "prima_total": 900000.0
              },
              {
                "empresa": "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA",
                "monto": 500000.0,
                "porcentaje": 27.98,
                "emitidas": 35,
                "porcentaje_emitidas": 29.17,
                "emitidas_mismo_periodo": 25,
                "emitidas_arrastre_pasado": 10,
                "prima_mismo_periodo": 400000.0,
                "prima_arrastre_pasado": 100000.0,
                "prima_total": 500000.0
              },
              {
                "empresa": "OTROS",
                "monto": 386920.2,
                "porcentaje": 21.65,
                "emitidas": 25,
                "porcentaje_emitidas": 20.83,
                "emitidas_mismo_periodo": 15,
                "emitidas_arrastre_pasado": 10,
                "prima_mismo_periodo": 200000.0,
                "prima_arrastre_pasado": 186920.2,
                "prima_total": 386920.2
              }
            ]
          },
          {
            "ramo": "VIDA",
            "monto": 1618621.0,
            "porcentaje": 24.15,
            "emitidas": 51,
            "porcentaje_emitidas": 10.83,
            "emitidas_mismo_periodo": 33,
            "emitidas_arrastre_pasado": 18,
            "prima_mismo_periodo": 1048621.0,
            "prima_arrastre_pasado": 570000.0,
            "prima_total": 1618621.0,
            "distribucion_sub_ramo": [
              {
                "sub_ramo": "VIDAMAS",
                "monto": 1000000.0,
                "porcentaje": 61.78,
                "emitidas": 32,
                "porcentaje_emitidas": 62.75,
                "emitidas_mismo_periodo": 21,
                "emitidas_arrastre_pasado": 11,
                "prima_mismo_periodo": 650000.0,
                "prima_arrastre_pasado": 350000.0,
                "prima_total": 1000000.0
              },
              {
                "sub_ramo": "VIDA INDIVIDUAL",
                "monto": 618621.0,
                "porcentaje": 38.22,
                "emitidas": 19,
                "porcentaje_emitidas": 37.25,
                "emitidas_mismo_periodo": 12,
                "emitidas_arrastre_pasado": 7,
                "prima_mismo_periodo": 398621.0,
                "prima_arrastre_pasado": 220000.0,
                "prima_total": 618621.0
              }
            ],
            "distribucion_empresa": []
          }
        ]
      },
      "gestion_cohorte_creacion": { "leads_registrados": 416, "oportunidades_generadas": 851, "emisiones_mismo_periodo": 302, "oportunidades_en_proceso": 456, "oportunidades_no_emitidas": 93 },
      "eficiencia_prospeccion": { "tasa_conversion_prospecto_pct": 15.87, "tasa_cierre_prospeccion_pct": 4.09 },
      "eficiencia_comercial": { "tasa_cierre_oportunidad_pct": 35.49, "tasa_oportunidades_perdidas_pct": 10.93, "pct_origen_cuentas_existentes": 92.13, "pct_origen_prospectos": 7.87 },
      "metrica_financiera": { "monto_total_cotizado": 8098623.02, "monto_total_emitido": 6701733.33 }
    },
    "pagination": { "page": 0, "size": 20, "total_pages": 2, "total_records": 30 },
    "filtros_aplicados": { "sort_by": "prima_colocada", "order": "DESC", "periodo": "mensual", "fecha_inicio": null, "fecha_fin": null, "ramo": null, "puesto": ["Asesor", "Telemarketing"] }
  },
  "items": [
    {
      "posicion_ranking": 1,
      "vendedor": { "numero_asesor": "10056", "nombre_asesor": "Miguel Angel Nestor Lopez", "zona": "Sur", "puesto": "Asesor" },
      "metricas_operativas": {
        "leads_registrados": 0,
        "cotizaciones_generadas": 0,
        "oportunidades_generadas": 36,
        "polizas_emitidas": 55,
        "prima_colocada_total": 756128.26,
        "dias_promedio_emision": 7.6,
        "tasa_conversion_prospecto_pct": 0
      }
    }
  ]
}
```
