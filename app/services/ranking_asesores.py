"""
Servicio de Ranking Global de Asesores (Agente Lucía).

Arquitectura:
- obtener_roster_asesores: catálogo completo de asesores (Asesor_externo__c)
  + resolución de su User activo (para poder atribuirles Leads/Oportunidades).
- consultar_leads_globales / consultar_oportunidades_globales: traen en lote
  los registros de TODOS los asesores del roster (no de uno solo).
- Reutiliza construir_items_unificada (trazabilidad_asesor.py) para ensamblar
  los items de cada asesor a partir de su porción de los datos globales.
- calcular_metricas_asesor: métricas de negocio del ranking sobre los items
  de un asesor ya filtrados por rango de fechas.
- obtener_ranking_global: orquestador principal (solo lectura).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from simple_salesforce import Salesforce

from app.dependencias.sf_service import es_error_sesion, reautenticar_salesforce
from app.services.trazabilidad_asesor import (
    LEAD_FIELDS,
    OPPORTUNITY_FIELDS,
    RAMOS_VALIDOS,
    _MAX_IDS_POR_LOTE,
    _limpiar_registro,
    _normalizar_str,
    _parsear_fecha,
    consultar_cuentas_en_lote,
    consultar_folios_en_lote,
    construir_items_unificada,
)


# ─── Constantes ───────────────────────────────────────────────────

SORT_BY_VALIDOS = {
    "prima_colocada",
    "polizas_emitidas",
    "tasa_conversion",
    "dias_promedio_emision",
    "leads_registrados",
    "oportunidades_generadas",
    "general",
}

ORDER_VALIDOS = {"ASC", "DESC"}

PERIODO_VALIDOS = {"mensual", "trimestral", "anual", "historico_total"}

# Ventanas móviles desde "ahora" para cada periodo con nombre.
DIAS_POR_PERIODO = {
    "mensual": 30,
    "trimestral": 90,
    "anual": 365,
}

# Métricas que participan en sort_by='general' (promedio de posiciones).
# True = mayor es mejor (se rankea DESC); False = menor es mejor (ASC).
METRICAS_GENERAL = {
    "prima_colocada_total": True,
    "polizas_emitidas": True,
    "tasa_conversion_prospecto_pct": True,
    "dias_promedio_emision": False,
    "leads_registrados": True,
    "oportunidades_generadas": True,
}


def _query_all_con_reintento(sf: Salesforce, query: str):
    """
    Como query_con_reintento, pero usa sf.query_all() en vez de sf.query().

    sf.query() solo trae la primera página de resultados (máximo 2000
    registros de la API REST); las consultas de este módulo son globales
    (todos los asesores activos) y deliberadamente no acotan por fecha de
    inicio, así que fácilmente pueden superar ese límite. sf.query_all()
    pagina automáticamente (vía nextRecordsUrl) hasta traer todo.
    """
    try:
        return sf.query_all(query)
    except Exception as e:
        if es_error_sesion(e):
            print("Sesión expirada en consulta global. Re-autenticando y reintentando...")
            sf_nueva = reautenticar_salesforce()
            return sf_nueva.query_all(query)
        raise


# ─── Capa 0: Resolución de fechas ──────────────────────────────────

def resolver_rango_fechas(
    periodo: Optional[str],
    fecha_inicio: Optional[str],
    fecha_fin: Optional[str],
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    fecha_inicio/fecha_fin, si vienen, tienen prioridad total sobre periodo.
    Si no vienen, periodo decide una ventana móvil desde ahora (mensual=30d,
    trimestral=90d, anual=365d). historico_total (o ausencia de periodo)
    no acota fechas.
    """
    if fecha_inicio or fecha_fin:
        inicio = None
        fin = None
        if fecha_inicio:
            inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if fecha_fin:
            fin = datetime.strptime(fecha_fin, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        return inicio, fin

    if periodo in DIAS_POR_PERIODO:
        fin = datetime.now(timezone.utc)
        inicio = fin - timedelta(days=DIAS_POR_PERIODO[periodo])
        return inicio, fin

    return None, None


def _fecha_en_rango(fecha: Any, inicio: Optional[datetime], fin: Optional[datetime]) -> bool:
    """Verifica si una fecha cae dentro de [inicio, fin]."""
    dt = _parsear_fecha(fecha)
    if dt is None:
        return False
    if inicio and dt < inicio:
        return False
    if fin and dt > fin:
        return False
    return True


# ─── Capa 1: Roster de asesores ────────────────────────────────────

def _normalizar_numero_asesor(valor: Any) -> Optional[str]:
    """Normaliza Numero_de_asesor__c (numérico en SF) a string comparable con Alias."""
    if valor is None:
        return None
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def obtener_roster_asesores(sf: Salesforce) -> List[Dict[str, Any]]:
    """
    Roster de asesores ACTIVOS.

    Asesor_externo__c no tiene ningún campo de estatus/activo — la única
    señal real de actividad es User.IsActive. Por eso el roster se
    construye a partir de los User activos con Alias definido, y se
    enriquece con nombre/zona desde Asesor_externo__c vía
    Numero_de_asesor__c = Alias.

    Un User activo sin un Asesor_externo__c correspondiente no entra al
    roster (no es un asesor de venta, es coincidencia de campo).
    """
    query_users = "SELECT Id, Alias, Name FROM User WHERE IsActive = True AND Alias != null"
    result_users = _query_all_con_reintento(sf, query_users)
    usuarios_activos = [_limpiar_registro(r) for r in result_users.get("records", []) if r.get("Alias")]

    query_asesores = "SELECT Id, Name, Numero_de_asesor__c, Zona__c, Puesto__c FROM Asesor_externo__c"
    result_asesores = _query_all_con_reintento(sf, query_asesores)
    asesores_por_numero: Dict[str, Dict[str, Any]] = {}
    for r in result_asesores.get("records", []):
        r = _limpiar_registro(r)
        numero = _normalizar_numero_asesor(r.get("Numero_de_asesor__c"))
        if numero:
            asesores_por_numero[numero] = r

    roster = []
    for user in usuarios_activos:
        alias = user["Alias"]
        asesor_externo = asesores_por_numero.get(alias)
        if not asesor_externo:
            continue

        roster.append({
            "numero_asesor": alias,
            "nombre_asesor": _normalizar_str(asesor_externo.get("Name")) or _normalizar_str(user.get("Name")),
            "zona": _normalizar_str(asesor_externo.get("Zona__c")),
            "puesto": _normalizar_str(asesor_externo.get("Puesto__c")),
            "user_id": user["Id"],
        })
    return roster


# ─── Capa 2: Consultas masivas (todos los asesores del roster) ─────

def consultar_leads_globales(
    sf: Salesforce,
    user_ids: List[str],
    fecha_fin: Optional[datetime],
) -> List[Dict[str, Any]]:
    """
    Consulta los Leads de todos los asesores (user_ids) en lote.

    Solo se acota por CreatedDate <= fecha_fin (cuando aplica): nada creado
    después de fecha_fin puede tener un folio con ClosedDate dentro del
    rango, así que es un límite seguro. No se acota por fecha_inicio a
    propósito: un Lead creado antes del rango puede tener un folio cuyo
    ClosedDate sí caiga dentro. El recorte fino ("cualquier fecha en el
    rango") se hace después en memoria, sobre los items ya ensamblados.
    """
    if not user_ids:
        return []

    leads = []
    for i in range(0, len(user_ids), _MAX_IDS_POR_LOTE):
        lote_ids = user_ids[i:i + _MAX_IDS_POR_LOTE]
        ids_str = ", ".join(f"'{uid}'" for uid in lote_ids)
        condiciones = [f"OwnerId IN ({ids_str})"]
        if fecha_fin:
            condiciones.append(f"CreatedDate <= {fecha_fin.strftime('%Y-%m-%dT%H:%M:%SZ')}")

        where_clause = " AND ".join(condiciones)
        query = f"SELECT {LEAD_FIELDS} FROM Lead WHERE {where_clause}"
        result = _query_all_con_reintento(sf, query)
        leads.extend(_limpiar_registro(r) for r in result.get("records", []))

    return leads


def consultar_oportunidades_globales(
    sf: Salesforce,
    user_ids: List[str],
    fecha_fin: Optional[datetime],
) -> List[Dict[str, Any]]:
    """Consulta las Oportunidades de todos los asesores en lote. Mismo criterio que Leads."""
    if not user_ids:
        return []

    oportunidades = []
    for i in range(0, len(user_ids), _MAX_IDS_POR_LOTE):
        lote_ids = user_ids[i:i + _MAX_IDS_POR_LOTE]
        ids_str = ", ".join(f"'{uid}'" for uid in lote_ids)
        condiciones = [f"OwnerId IN ({ids_str})"]
        if fecha_fin:
            condiciones.append(f"CreatedDate <= {fecha_fin.strftime('%Y-%m-%dT%H:%M:%SZ')}")

        where_clause = " AND ".join(condiciones)
        query = f"SELECT {OPPORTUNITY_FIELDS} FROM Opportunity WHERE {where_clause}"
        result = _query_all_con_reintento(sf, query)
        oportunidades.extend(_limpiar_registro(r) for r in result.get("records", []))

    return oportunidades


# ─── Capa 3: Agrupar por asesor y ensamblar items ──────────────────

def agrupar_por_asesor(
    roster: List[Dict[str, Any]],
    leads: List[Dict[str, Any]],
    oportunidades: List[Dict[str, Any]],
    folios_por_opp: Dict[str, List[Dict[str, Any]]],
    cuentas: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Para cada asesor del roster, filtra su porción de leads/oportunidades y
    ensambla sus items (reutilizando construir_items_unificada).

    No se filtra por rango de fechas aquí: cada métrica en
    calcular_metricas_asesor decide, con la fecha propia de su entidad
    (CreatedDate del Lead/Opportunity, ClosedDate del Case), si un
    registro cuenta o no en el periodo — ver el docstring de esa función.
    """
    leads_por_owner: Dict[str, List[Dict[str, Any]]] = {}
    for lead in leads:
        owner_id = lead.get("OwnerId")
        if owner_id:
            leads_por_owner.setdefault(owner_id, []).append(lead)

    opps_por_owner: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for opp in oportunidades:
        owner_id = opp.get("OwnerId")
        if owner_id:
            opps_por_owner.setdefault(owner_id, {})[opp["Id"]] = opp

    resultado = []
    for asesor in roster:
        user_id = asesor.get("user_id")
        leads_asesor = leads_por_owner.get(user_id, []) if user_id else []
        opps_asesor = opps_por_owner.get(user_id, {}) if user_id else {}

        items = construir_items_unificada(leads_asesor, opps_asesor, folios_por_opp, cuentas)

        resultado.append({
            "numero_asesor": asesor["numero_asesor"],
            "nombre_asesor": asesor["nombre_asesor"],
            "zona": asesor["zona"],
            "puesto": asesor["puesto"],
            "items": items,
        })

    return resultado


def _item_coincide_ramo(item: Dict[str, Any], ramos: set) -> bool:
    """
    True si el prospecto, la oportunidad (Ramos_de_interes__c) o algún
    folio (Ramo__c) del item coincide con alguno de los ramos pedidos.
    Mismo criterio que filtrar_por_ramo (trazabilidad_asesor.py), pero
    soporta varios ramos a la vez.
    """
    prospecto = item.get("prospecto") or {}
    if prospecto.get("ramos_interes") in ramos:
        return True

    opp = item.get("oportunidad")
    if opp and opp.get("ramos_interes") in ramos:
        return True

    if any(folio.get("ramo") in ramos for folio in item.get("folios_emision", [])):
        return True

    return False


def filtrar_grupos_por_ramo(
    grupos: List[Dict[str, Any]],
    ramos: List[str],
) -> List[Dict[str, Any]]:
    """Filtra los items de cada asesor a solo los que coincidan con alguno de los ramos."""
    ramos_set = set(ramos)
    for grupo in grupos:
        grupo["items"] = [item for item in grupo["items"] if _item_coincide_ramo(item, ramos_set)]
    return grupos


def filtrar_roster_por_puesto(
    roster: List[Dict[str, Any]],
    puestos: List[str],
) -> List[Dict[str, Any]]:
    """Filtra el roster a solo los asesores cuyo Puesto__c esté en la lista pedida."""
    puestos_set = {p.strip() for p in puestos}
    return [a for a in roster if (a.get("puesto") or "").strip() in puestos_set]


# ─── Capa 4: Métricas de negocio del ranking ───────────────────────

def _resolver_origen_item(item: Dict[str, Any]) -> str:
    """
    Origen_de_oportunidad__c si el item tiene oportunidad, LeadSource si no.
    'Sin identificar' si el campo aplicable viene vacío.
    """
    opp = item.get("oportunidad")
    if opp:
        origen = opp.get("origen_oportunidad")
    else:
        prospecto = item.get("prospecto") or {}
        origen = prospecto.get("lead_source")
    return origen or "Sin identificar"


def calcular_metricas_asesor(
    items: List[Dict[str, Any]],
    inicio: Optional[datetime],
    fin: Optional[datetime],
) -> Dict[str, Any]:
    """
    Calcula las métricas del ranking para un asesor, sobre TODOS sus items
    (sin pre-filtrar), aplicando el rango de fechas por métrica según la
    fecha propia de cada entidad — distinción de negocio entre
    "producción del periodo" (lo cerrado/emitido, incluye arrastre de
    cohortes anteriores) y "gestión de cohorte" (lo creado en el periodo,
    y qué tan bien le fue):

    - leads_registrados / tasa_conversion_prospecto_pct: Lead.CreatedDate
      en [inicio, fin].
    - oportunidades_generadas / cotizaciones_generadas / distribucion_origen /
      emisiones_mismo_periodo / oportunidades_en_proceso / oportunidades_no_emitidas:
      Opportunity.CreatedDate en [inicio, fin] (cohorte) — 'emisiones_mismo_periodo'
      exige además que el folio emitido de esa oportunidad tenga su propio
      ClosedDate también en [inicio, fin] (si cerró después, sigue "en proceso"
      al momento de esta consulta).
    - polizas_emitidas / prima_colocada_total / desglose_prima_ramo /
      dias_promedio_emision / total_canceladas / total_vigentes:
      Case.ClosedDate en [inicio, fin] — producción real del periodo, sin
      importar cuándo se creó la oportunidad que lo originó (arrastre).

    'metricas_operativas' (forma plana original) se conserva sin cambios
    por compatibilidad; 'produccion_periodo_cierre' / 'gestion_cohorte_creacion'
    / 'eficiencia_conversion' / 'metrica_financiera' son aditivos.

    Incluye una clave interna '_agregados_internos' (no se expone en el
    JSON final) con los valores crudos necesarios para que
    calcular_resumen_general pueda re-agregar el total de la empresa de
    forma exacta, sin reconstruir promedios a partir de porcentajes ya
    redondeados.
    """
    leads_registrados = 0
    convertidos = 0
    total_oportunidades = 0
    cotizaciones_generadas = 0
    polizas_emitidas = 0
    prima_colocada_total = 0.0
    prima_por_ramo = {r: 0.0 for r in RAMOS_VALIDOS}
    dias_emision = []
    origenes: Dict[str, Dict[str, int]] = {}

    monto_cotizado_cohorte = 0.0
    emisiones_mismo_periodo = 0
    emisiones_provenientes_de_lead = 0
    oportunidades_no_emitidas = 0
    oportunidades_en_proceso = 0
    polizas_canceladas = 0
    polizas_vigentes = 0

    # Cohorte: origen de las oportunidades_generadas (Lead vs. cuenta existente).
    cohorte_prospectos = 0
    cohorte_cuentas_existentes = 0

    # Producción del periodo: de los folios EMITIDOS (ClosedDate en rango,
    # incluye arrastre), composición por origen e inmediatez.
    prod_prospectos_nuevos = 0
    prod_cuentas_existentes = 0
    prod_mismo_periodo = 0
    prod_arrastre_pasado = 0

    for item in items:
        prospecto = item.get("prospecto")
        prospecto_en_rango = prospecto is not None and _fecha_en_rango(
            prospecto.get("created_date"), inicio, fin
        )
        if prospecto_en_rango:
            leads_registrados += 1
            if prospecto.get("is_converted"):
                convertidos += 1

        opp = item.get("oportunidad")
        opp_en_rango = opp is not None and _fecha_en_rango(opp.get("created_date"), inicio, fin)
        origen_registro = item.get("origen_registro")

        if opp_en_rango:
            total_oportunidades += 1
            if (opp.get("stage_name") or "").strip().lower() == "cotización":
                cotizaciones_generadas += 1
            monto_cotizado_cohorte += opp.get("prima_total_cotizada") or 0.0

            if origen_registro == "PROSPECTO_CONVERTIDO":
                cohorte_prospectos += 1
            else:
                cohorte_cuentas_existentes += 1

        # distribucion_origen: un origen (por canal) por item, contado en el
        # mismo momento en que el item "nace" como oportunidad o como
        # prospecto sin oportunidad. 'emitidas' se completa más abajo.
        origen_item = None
        if opp_en_rango or (prospecto_en_rango and opp is None):
            origen_item = _resolver_origen_item(item)
            origenes.setdefault(origen_item, {"total": 0, "emitidas": 0})
            origenes[origen_item]["total"] += 1

        fecha_origen = None
        if origen_registro == "PROSPECTO_CONVERTIDO" and prospecto:
            fecha_origen = _parsear_fecha(prospecto.get("created_date"))
        elif opp:
            fecha_origen = _parsear_fecha(opp.get("created_date"))

        # Clasificación del resultado de la oportunidad. Preferencia: si hay
        # folio(s), el folio manda (incluyendo su propio ClosedDate para
        # "mismo periodo"). Solo se usa el StageName de la oportunidad como
        # respaldo cuando NO existe ningún folio — algunas oportunidades
        # "Póliza no emitida" nunca llegan a tener un Case asociado (se
        # descartan antes de generar folio), y sin este respaldo se
        # subcontarían como "en proceso".
        folios = item.get("folios_emision", [])
        if folios:
            tiene_emitida_en_periodo = False
            tiene_no_emitida = False
        else:
            stage = (opp.get("stage_name") or "").strip().lower() if opp else ""
            tiene_emitida_en_periodo = stage == "póliza emitida"
            tiene_no_emitida = stage == "póliza no emitida"

        for folio in folios:
            fecha_cierre = _parsear_fecha(folio.get("closed_date"))
            folio_en_rango = _fecha_en_rango(folio.get("closed_date"), inicio, fin)

            if folio.get("poliza_emitida"):
                if folio_en_rango:
                    tiene_emitida_en_periodo = True
                    polizas_emitidas += 1
                    monto = folio.get("poliza_prima_total") or 0.0
                    prima_colocada_total += monto
                    ramo = folio.get("ramo")
                    if ramo in prima_por_ramo:
                        prima_por_ramo[ramo] += monto

                    poliza_status = (folio.get("poliza_status") or "").strip().lower()
                    if poliza_status == "cancelado":
                        polizas_canceladas += 1
                    elif poliza_status == "vigente":
                        polizas_vigentes += 1

                    # Composición por origen del registro (Lead vs. Cuenta existente).
                    if origen_registro == "PROSPECTO_CONVERTIDO":
                        prod_prospectos_nuevos += 1
                    else:
                        prod_cuentas_existentes += 1

                    # Composición por inmediatez: la oportunidad nació en el
                    # mismo rango consultado, o viene de un periodo pasado.
                    if opp_en_rango:
                        prod_mismo_periodo += 1
                    else:
                        prod_arrastre_pasado += 1

                    if fecha_origen and fecha_cierre:
                        dias = (fecha_cierre - fecha_origen).days
                        if dias >= 0:
                            dias_emision.append(dias)

            elif folio.get("poliza_no_emitida"):
                tiene_no_emitida = True

        if opp_en_rango:
            if tiene_emitida_en_periodo:
                emisiones_mismo_periodo += 1
                if origen_registro == "PROSPECTO_CONVERTIDO":
                    emisiones_provenientes_de_lead += 1
            elif tiene_no_emitida:
                oportunidades_no_emitidas += 1
            else:
                oportunidades_en_proceso += 1

        if origen_item is not None and tiene_emitida_en_periodo:
            origenes[origen_item]["emitidas"] += 1

    dias_promedio_emision = round(sum(dias_emision) / len(dias_emision), 1) if dias_emision else None
    tasa_conversion_prospecto_pct = round(convertidos / leads_registrados * 100, 2) if leads_registrados else 0.0
    tasa_cierre_prospeccion_pct = (
        round(emisiones_provenientes_de_lead / leads_registrados * 100, 2) if leads_registrados else 0.0
    )
    tasa_cierre_oportunidad_pct = (
        round(emisiones_mismo_periodo / total_oportunidades * 100, 2) if total_oportunidades else 0.0
    )
    tasa_oportunidades_perdidas_pct = (
        round(oportunidades_no_emitidas / total_oportunidades * 100, 2) if total_oportunidades else 0.0
    )
    pct_origen_cuentas_existentes = (
        round(cohorte_cuentas_existentes / total_oportunidades * 100, 2) if total_oportunidades else 0.0
    )
    pct_origen_prospectos = (
        round(cohorte_prospectos / total_oportunidades * 100, 2) if total_oportunidades else 0.0
    )
    ticket_promedio_prima = round(prima_colocada_total / polizas_emitidas, 2) if polizas_emitidas else 0.0

    total_origenes = sum(datos["total"] for datos in origenes.values())
    distribucion_origen = [
        {
            "origen": origen,
            "total": datos["total"],
            "porcentaje": round(datos["total"] / total_origenes * 100, 2) if total_origenes else 0.0,
            "emitidas": datos["emitidas"],
            "porcentaje_emitidas": round(datos["emitidas"] / datos["total"] * 100, 2) if datos["total"] else 0.0,
        }
        for origen, datos in sorted(origenes.items(), key=lambda x: x[1]["total"], reverse=True)
    ]

    distribucion_ramo_emisiones = [
        {
            "ramo": ramo,
            "monto": round(monto, 2),
            "porcentaje": round(monto / prima_colocada_total * 100, 2) if prima_colocada_total else 0.0,
        }
        for ramo, monto in prima_por_ramo.items()
    ]

    return {
        "metricas_operativas": {
            "leads_registrados": leads_registrados,
            "cotizaciones_generadas": cotizaciones_generadas,
            "oportunidades_generadas": total_oportunidades,
            "polizas_emitidas": polizas_emitidas,
            "prima_colocada_total": round(prima_colocada_total, 2),
            "dias_promedio_emision": dias_promedio_emision,
            "tasa_conversion_prospecto_pct": tasa_conversion_prospecto_pct,
        },
        "produccion_periodo_cierre": {
            "polizas_emitidas_total": polizas_emitidas,
            "prima_colocada_total": round(prima_colocada_total, 2),
            "dias_promedio_emision": dias_promedio_emision,
            "total_canceladas": polizas_canceladas,
            "total_vigentes": polizas_vigentes,
            "ticket_promedio_prima": ticket_promedio_prima,
            "composicion_origen_emisiones": {
                "prospectos_nuevos": prod_prospectos_nuevos,
                "cuentas_existentes": prod_cuentas_existentes,
                "pct_origen_prospectos": (
                    round(prod_prospectos_nuevos / polizas_emitidas * 100, 2) if polizas_emitidas else 0.0
                ),
                "pct_origen_cuentas_existentes": (
                    round(prod_cuentas_existentes / polizas_emitidas * 100, 2) if polizas_emitidas else 0.0
                ),
            },
            "composicion_inmediatez_emisiones": {
                "mismo_periodo": prod_mismo_periodo,
                "arrastre_pasado": prod_arrastre_pasado,
                "pct_mismo_periodo": (
                    round(prod_mismo_periodo / polizas_emitidas * 100, 2) if polizas_emitidas else 0.0
                ),
                "pct_arrastre_pasado": (
                    round(prod_arrastre_pasado / polizas_emitidas * 100, 2) if polizas_emitidas else 0.0
                ),
            },
            "distribucion_ramo_emisiones": distribucion_ramo_emisiones,
        },
        "gestion_cohorte_creacion": {
            "leads_registrados": leads_registrados,
            "oportunidades_generadas": total_oportunidades,
            "emisiones_mismo_periodo": emisiones_mismo_periodo,
            "oportunidades_en_proceso": oportunidades_en_proceso,
            "oportunidades_no_emitidas": oportunidades_no_emitidas,
        },
        "eficiencia_prospeccion": {
            "tasa_conversion_prospecto_pct": tasa_conversion_prospecto_pct,
            "tasa_cierre_prospeccion_pct": tasa_cierre_prospeccion_pct,
        },
        "eficiencia_comercial": {
            "tasa_cierre_oportunidad_pct": tasa_cierre_oportunidad_pct,
            "tasa_oportunidades_perdidas_pct": tasa_oportunidades_perdidas_pct,
            "pct_origen_cuentas_existentes": pct_origen_cuentas_existentes,
            "pct_origen_prospectos": pct_origen_prospectos,
        },
        "metrica_financiera": {
            "monto_total_cotizado": round(monto_cotizado_cohorte, 2),
            "monto_total_emitido": round(prima_colocada_total, 2),
        },
        "distribucion_origen": distribucion_origen,
        "_agregados_internos": {
            "convertidos": convertidos,
            "suma_dias_emision": sum(dias_emision),
            "conteo_dias_emision": len(dias_emision),
            "emisiones_mismo_periodo": emisiones_mismo_periodo,
            "emisiones_provenientes_de_lead": emisiones_provenientes_de_lead,
            "total_oportunidades": total_oportunidades,
            "polizas_canceladas": polizas_canceladas,
            "polizas_vigentes": polizas_vigentes,
            "monto_cotizado_cohorte": monto_cotizado_cohorte,
            "cohorte_prospectos": cohorte_prospectos,
            "cohorte_cuentas_existentes": cohorte_cuentas_existentes,
            "prod_prospectos_nuevos": prod_prospectos_nuevos,
            "prod_cuentas_existentes": prod_cuentas_existentes,
            "prod_mismo_periodo": prod_mismo_periodo,
            "prod_arrastre_pasado": prod_arrastre_pasado,
        },
    }


# ─── Capa 5: Ranking (ordenamiento y "general") ────────────────────

def _valor_orden(asesor: Dict[str, Any], campo: str) -> float:
    """None se manda al fondo del orden, sin importar la dirección."""
    valor = asesor["metricas_operativas"].get(campo)
    return valor if valor is not None else float("-inf")


def _asignar_ranking_general(asesores: List[Dict[str, Any]]) -> None:
    """
    Promedio de la posición (rank) de cada asesor en cada métrica base —
    no un promedio de valores crudos, que mezclarían escalas incompatibles
    (dinero, días, porcentajes, conteos). Un asesor sin dato en una
    métrica (ej. sin folios emitidos) recibe la peor posición posible en
    esa métrica. Escribe '_ranking_general_score' (menor = mejor lugar).
    """
    n = len(asesores)
    if n == 0:
        return

    posiciones_acumuladas = [[] for _ in asesores]

    for campo, mayor_es_mejor in METRICAS_GENERAL.items():
        indices_con_dato = [i for i, a in enumerate(asesores) if a["metricas_operativas"].get(campo) is not None]
        indices_sin_dato = [i for i, a in enumerate(asesores) if a["metricas_operativas"].get(campo) is None]

        indices_con_dato.sort(
            key=lambda i: asesores[i]["metricas_operativas"][campo],
            reverse=mayor_es_mejor,
        )

        for posicion, i in enumerate(indices_con_dato, start=1):
            posiciones_acumuladas[i].append(posicion)
        for i in indices_sin_dato:
            posiciones_acumuladas[i].append(n)

    for i, asesor in enumerate(asesores):
        asesor["_ranking_general_score"] = sum(posiciones_acumuladas[i]) / len(posiciones_acumuladas[i])


def ordenar_asesores(asesores: List[Dict[str, Any]], sort_by: str, order: str) -> List[Dict[str, Any]]:
    if sort_by == "general":
        _asignar_ranking_general(asesores)
        asesores.sort(key=lambda a: a["_ranking_general_score"])
        return asesores

    campo_por_sort = {
        "prima_colocada": "prima_colocada_total",
        "polizas_emitidas": "polizas_emitidas",
        "tasa_conversion": "tasa_conversion_prospecto_pct",
        "dias_promedio_emision": "dias_promedio_emision",
        "leads_registrados": "leads_registrados",
        "oportunidades_generadas": "oportunidades_generadas",
    }
    campo = campo_por_sort[sort_by]
    reverse = (order == "DESC")
    asesores.sort(key=lambda a: _valor_orden(a, campo), reverse=reverse)
    return asesores


# ─── Capa 6: Resumen general de la empresa ─────────────────────────

def calcular_resumen_general(asesores: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Agrega los totales de la empresa sobre TODOS los asesores evaluados, antes de paginar."""
    total_asesores_evaluados = len(asesores)
    leads_registrados = sum(a["metricas_operativas"]["leads_registrados"] for a in asesores)
    cotizaciones_generadas = sum(a["metricas_operativas"]["cotizaciones_generadas"] for a in asesores)
    polizas_emitidas = sum(a["metricas_operativas"]["polizas_emitidas"] for a in asesores)
    prima_colocada_total = sum(a["metricas_operativas"]["prima_colocada_total"] for a in asesores)

    convertidos_totales = sum(a["_agregados_internos"]["convertidos"] for a in asesores)
    tasa_conversion_global_pct = (
        round(convertidos_totales / leads_registrados * 100, 2) if leads_registrados else 0.0
    )

    suma_dias = sum(a["_agregados_internos"]["suma_dias_emision"] for a in asesores)
    conteo_dias = sum(a["_agregados_internos"]["conteo_dias_emision"] for a in asesores)
    dias_promedio_emision_global = round(suma_dias / conteo_dias, 1) if conteo_dias else None

    origenes_totales: Dict[str, Dict[str, int]] = {}
    for a in asesores:
        for entry in a["distribucion_origen"]:
            datos = origenes_totales.setdefault(entry["origen"], {"total": 0, "emitidas": 0})
            datos["total"] += entry["total"]
            datos["emitidas"] += entry["emitidas"]
    total_origenes = sum(datos["total"] for datos in origenes_totales.values())
    distribucion_origen = [
        {
            "origen": origen,
            "total": datos["total"],
            "porcentaje": round(datos["total"] / total_origenes * 100, 2) if total_origenes else 0.0,
            "emitidas": datos["emitidas"],
            "porcentaje_emitidas": round(datos["emitidas"] / datos["total"] * 100, 2) if datos["total"] else 0.0,
        }
        for origen, datos in sorted(origenes_totales.items(), key=lambda x: x[1]["total"], reverse=True)
    ]

    # Distribución por puesto (Asesor_externo__c.Puesto__c): agrupa ASESORES
    # (no items) por su puesto.
    # - 'total' = oportunidades_generadas (cohorte: nacidas en el rango).
    # - 'emitidas' = TOTAL emitido en el rango por ese puesto, sin importar
    #   cuándo nació la oportunidad (= emitidas_mismo_periodo + emitidas_arrastre_pasado,
    #   mismo criterio que produccion_periodo_cierre.polizas_emitidas_total).
    # - 'porcentaje_emitidas' se calcula contra el total emitido de TODA la
    #   empresa (no contra 'total' de este puesto): 'total' es cohorte y
    #   'emitidas' es producción, son poblaciones distintas — dividir una
    #   entre la otra es lo que daba porcentajes absurdos (>100%) antes.
    #   Aquí sí es una proporción válida (participación de este puesto en
    #   la producción total), siempre <= 100%.
    puestos_totales: Dict[str, Dict[str, int]] = {}
    for a in asesores:
        puesto = a.get("puesto") or "Sin puesto"
        datos = puestos_totales.setdefault(
            puesto,
            {"total": 0, "emitidas_mismo_periodo": 0, "emitidas_arrastre_pasado": 0},
        )
        datos["total"] += a["gestion_cohorte_creacion"]["oportunidades_generadas"]
        datos["emitidas_mismo_periodo"] += a["_agregados_internos"]["prod_mismo_periodo"]
        datos["emitidas_arrastre_pasado"] += a["_agregados_internos"]["prod_arrastre_pasado"]
    total_puestos = sum(datos["total"] for datos in puestos_totales.values())
    distribucion_puesto = [
        {
            "puesto": puesto,
            "total": datos["total"],
            "porcentaje": round(datos["total"] / total_puestos * 100, 2) if total_puestos else 0.0,
            "emitidas": datos["emitidas_mismo_periodo"] + datos["emitidas_arrastre_pasado"],
            "porcentaje_emitidas": (
                round(
                    (datos["emitidas_mismo_periodo"] + datos["emitidas_arrastre_pasado"]) / polizas_emitidas * 100, 2
                )
                if polizas_emitidas else 0.0
            ),
            "emitidas_mismo_periodo": datos["emitidas_mismo_periodo"],
            "emitidas_arrastre_pasado": datos["emitidas_arrastre_pasado"],
        }
        for puesto, datos in sorted(puestos_totales.items(), key=lambda x: x[1]["total"], reverse=True)
    ]

    # ── Bloques: producción del periodo vs. cohorte, a nivel empresa ──
    total_canceladas = sum(a["_agregados_internos"]["polizas_canceladas"] for a in asesores)
    total_vigentes = sum(a["_agregados_internos"]["polizas_vigentes"] for a in asesores)

    oportunidades_generadas_total = sum(a["_agregados_internos"]["total_oportunidades"] for a in asesores)
    emisiones_mismo_periodo_total = sum(a["_agregados_internos"]["emisiones_mismo_periodo"] for a in asesores)
    emisiones_lead_total = sum(a["_agregados_internos"]["emisiones_provenientes_de_lead"] for a in asesores)
    oportunidades_no_emitidas_total = sum(
        a["gestion_cohorte_creacion"]["oportunidades_no_emitidas"] for a in asesores
    )
    oportunidades_en_proceso_total = sum(
        a["gestion_cohorte_creacion"]["oportunidades_en_proceso"] for a in asesores
    )
    monto_cotizado_total = sum(a["_agregados_internos"]["monto_cotizado_cohorte"] for a in asesores)

    cohorte_prospectos_total = sum(a["_agregados_internos"]["cohorte_prospectos"] for a in asesores)
    cohorte_cuentas_existentes_total = sum(a["_agregados_internos"]["cohorte_cuentas_existentes"] for a in asesores)

    prod_prospectos_nuevos_total = sum(a["_agregados_internos"]["prod_prospectos_nuevos"] for a in asesores)
    prod_cuentas_existentes_total = sum(a["_agregados_internos"]["prod_cuentas_existentes"] for a in asesores)
    prod_mismo_periodo_total = sum(a["_agregados_internos"]["prod_mismo_periodo"] for a in asesores)
    prod_arrastre_pasado_total = sum(a["_agregados_internos"]["prod_arrastre_pasado"] for a in asesores)

    tasa_cierre_oportunidad_global_pct = (
        round(emisiones_mismo_periodo_total / oportunidades_generadas_total * 100, 2)
        if oportunidades_generadas_total else 0.0
    )
    tasa_cierre_prospeccion_global_pct = (
        round(emisiones_lead_total / leads_registrados * 100, 2) if leads_registrados else 0.0
    )
    tasa_oportunidades_perdidas_global_pct = (
        round(oportunidades_no_emitidas_total / oportunidades_generadas_total * 100, 2)
        if oportunidades_generadas_total else 0.0
    )
    pct_origen_cuentas_existentes_global = (
        round(cohorte_cuentas_existentes_total / oportunidades_generadas_total * 100, 2)
        if oportunidades_generadas_total else 0.0
    )
    pct_origen_prospectos_global = (
        round(cohorte_prospectos_total / oportunidades_generadas_total * 100, 2)
        if oportunidades_generadas_total else 0.0
    )
    ticket_promedio_prima_global = round(prima_colocada_total / polizas_emitidas, 2) if polizas_emitidas else 0.0

    # Distribución de ramo homologada con el endpoint por-asesor: se lee de
    # produccion_periodo_cierre.distribucion_ramo_emisiones de cada asesor
    # (ya no hay un desglose_prima_ramo por separado — era el mismo dato).
    prima_por_ramo_totales = {r: 0.0 for r in RAMOS_VALIDOS}
    for a in asesores:
        for entry in a["produccion_periodo_cierre"]["distribucion_ramo_emisiones"]:
            if entry["ramo"] in prima_por_ramo_totales:
                prima_por_ramo_totales[entry["ramo"]] += entry["monto"]
    distribucion_ramo_emisiones_global = [
        {
            "ramo": ramo,
            "monto": round(monto, 2),
            "porcentaje": round(monto / prima_colocada_total * 100, 2) if prima_colocada_total else 0.0,
        }
        for ramo, monto in prima_por_ramo_totales.items()
    ]

    return {
        "totales_operativos": {
            "total_asesores_evaluados": total_asesores_evaluados,
            "leads_registrados": leads_registrados,
            "cotizaciones_generadas": cotizaciones_generadas,
            "polizas_emitidas": polizas_emitidas,
            "prima_colocada_total": round(prima_colocada_total, 2),
        },
        "eficiencia_global": {
            "tasa_conversion_global_pct": tasa_conversion_global_pct,
            "dias_promedio_emision_global": dias_promedio_emision_global,
            "distribucion_origen": distribucion_origen,
            "distribucion_puesto": distribucion_puesto,
        },
        "produccion_periodo_cierre": {
            "polizas_emitidas_total": polizas_emitidas,
            "prima_colocada_total": round(prima_colocada_total, 2),
            "dias_promedio_emision": dias_promedio_emision_global,
            "total_canceladas": total_canceladas,
            "total_vigentes": total_vigentes,
            "ticket_promedio_prima": ticket_promedio_prima_global,
            "composicion_origen_emisiones": {
                "prospectos_nuevos": prod_prospectos_nuevos_total,
                "cuentas_existentes": prod_cuentas_existentes_total,
                "pct_origen_prospectos": (
                    round(prod_prospectos_nuevos_total / polizas_emitidas * 100, 2) if polizas_emitidas else 0.0
                ),
                "pct_origen_cuentas_existentes": (
                    round(prod_cuentas_existentes_total / polizas_emitidas * 100, 2) if polizas_emitidas else 0.0
                ),
            },
            "composicion_inmediatez_emisiones": {
                "mismo_periodo": prod_mismo_periodo_total,
                "arrastre_pasado": prod_arrastre_pasado_total,
                "pct_mismo_periodo": (
                    round(prod_mismo_periodo_total / polizas_emitidas * 100, 2) if polizas_emitidas else 0.0
                ),
                "pct_arrastre_pasado": (
                    round(prod_arrastre_pasado_total / polizas_emitidas * 100, 2) if polizas_emitidas else 0.0
                ),
            },
            "distribucion_ramo_emisiones": distribucion_ramo_emisiones_global,
        },
        "gestion_cohorte_creacion": {
            "leads_registrados": leads_registrados,
            "oportunidades_generadas": oportunidades_generadas_total,
            "emisiones_mismo_periodo": emisiones_mismo_periodo_total,
            "oportunidades_en_proceso": oportunidades_en_proceso_total,
            "oportunidades_no_emitidas": oportunidades_no_emitidas_total,
        },
        "eficiencia_prospeccion": {
            "tasa_conversion_prospecto_pct": tasa_conversion_global_pct,
            "tasa_cierre_prospeccion_pct": tasa_cierre_prospeccion_global_pct,
        },
        "eficiencia_comercial": {
            "tasa_cierre_oportunidad_pct": tasa_cierre_oportunidad_global_pct,
            "tasa_oportunidades_perdidas_pct": tasa_oportunidades_perdidas_global_pct,
            "pct_origen_cuentas_existentes": pct_origen_cuentas_existentes_global,
            "pct_origen_prospectos": pct_origen_prospectos_global,
        },
        "metrica_financiera": {
            "monto_total_cotizado": round(monto_cotizado_total, 2),
            "monto_total_emitido": round(prima_colocada_total, 2),
        },
    }


# ─── Orquestador principal ─────────────────────────────────────────

def obtener_ranking_global(
    sf: Salesforce,
    sort_by: str = "prima_colocada",
    order: str = "DESC",
    periodo: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    ramo: Optional[List[str]] = None,
    puesto: Optional[List[str]] = None,
    page: int = 0,
    size: int = 20,
) -> Dict[str, Any]:
    """
    Flujo:
    1. Resuelve el rango de fechas (fecha_inicio/fecha_fin > periodo).
    2. Trae el roster completo de asesores y resuelve sus User Ids.
       Si se pidió filtrar por puesto, se filtra el roster aquí (antes de
       consultar Leads/Oportunidades, para no traer datos de más).
    3. Consulta Leads y Oportunidades de TODOS los asesores en lote.
    4. Consulta Folios y Cuentas en lote (a partir de las oportunidades).
    5. Agrupa por asesor y ensambla items (reutilizando construir_items_unificada).
       Si se pidió filtrar por ramo, se filtran los items de cada asesor aquí.
    6. Calcula métricas de negocio por asesor (cada métrica filtra por la
       fecha propia de su entidad; ver docstring de calcular_metricas_asesor).
    7. Ordena según sort_by/order.
    8. Calcula el resumen general de la empresa (sobre el total filtrado, sin paginar).
    9. Pagina en memoria.
    """
    inicio, fin = resolver_rango_fechas(periodo, fecha_inicio, fecha_fin)

    roster = obtener_roster_asesores(sf)
    if puesto:
        roster = filtrar_roster_por_puesto(roster, puesto)

    user_ids = [a["user_id"] for a in roster if a.get("user_id")]

    leads = consultar_leads_globales(sf, user_ids, fin)
    oportunidades = consultar_oportunidades_globales(sf, user_ids, fin)

    opp_ids = [opp["Id"] for opp in oportunidades]
    folios_por_opp = consultar_folios_en_lote(sf, opp_ids)

    account_ids = [lead["ConvertedAccountId"] for lead in leads if lead.get("ConvertedAccountId")]
    cuentas = consultar_cuentas_en_lote(sf, account_ids)

    grupos = agrupar_por_asesor(roster, leads, oportunidades, folios_por_opp, cuentas)
    if ramo:
        grupos = filtrar_grupos_por_ramo(grupos, ramo)

    asesores = []
    for grupo in grupos:
        metricas = calcular_metricas_asesor(grupo["items"], inicio, fin)
        asesores.append({
            "numero_asesor": grupo["numero_asesor"],
            "nombre_asesor": grupo["nombre_asesor"],
            "zona": grupo["zona"],
            "puesto": grupo["puesto"],
            **metricas,
        })

    asesores = ordenar_asesores(asesores, sort_by, order)
    resumen_general_empresa = calcular_resumen_general(asesores)

    total_records = len(asesores)
    start = page * size
    end = start + size
    asesores_pagina = asesores[start:end]
    total_pages = (total_records + size - 1) // size if size > 0 else 0

    # Leaderboard plano: solo lo necesario para ordenar/mostrar la tabla de
    # ranking. El detalle analítico por asesor (desglose por ramo, origen,
    # producción vs. cohorte) vive en /api/v1/seguimiento/asesor —
    # el frontend lo consulta al dar clic en un asesor, no aquí.
    items_respuesta = [
        {
            "posicion_ranking": idx,
            "vendedor": {
                "numero_asesor": a["numero_asesor"],
                "nombre_asesor": a["nombre_asesor"],
                "zona": a["zona"],
                "puesto": a["puesto"],
            },
            "metricas_operativas": a["metricas_operativas"],
        }
        for idx, a in enumerate(asesores_pagina, start=start + 1)
    ]

    return {
        "status": "success",
        "meta": {
            "fecha_generacion": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "resumen_general_empresa": resumen_general_empresa,
            "pagination": {
                "page": page,
                "size": size,
                "total_pages": total_pages,
                "total_records": total_records,
            },
            "filtros_aplicados": {
                "sort_by": sort_by,
                "order": order,
                "periodo": periodo,
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "ramo": ramo,
                "puesto": puesto,
            },
        },
        "items": items_respuesta,
    }
