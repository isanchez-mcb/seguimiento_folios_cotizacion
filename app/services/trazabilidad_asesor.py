"""
Servicio de Trazabilidad End-to-End de Asesores (Agente Lucía).

Arquitectura por capas (SRP / SOLID):
- obtener_user_id_por_alias: obtiene el User activo cuyo Alias = numero_asesor
- obtener_nombre_asesor: obtiene el nombre del asesor (User o Asesor_externo__c)
- consultar_leads_por_asesor: consulta Leads por OwnerId (propietario principal)
- consultar_oportunidades_en_lote: consulta Oportunidades relacionadas en lote
- consultar_folios_en_lote: consulta Folios (Case) vinculados a oportunidades
- mapear_prospecto / mapear_oportunidad / mapear_folio: mapeo de registros SF a dicts
- construir_items: ensambla la matriz de trazabilidad aplanada
- calcular_kpis: calcula métricas agregadas
- filtrar_por_periodo: filtra items por periodo (Lead, Oportunidad o Folio)
- paginar_items: aplica paginación en memoria
- obtener_trazabilidad_asesor: orquestador principal (solo lectura)
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from simple_salesforce import Salesforce

from app.dependencias.sf_service import query_con_reintento


# ─── Constantes ───────────────────────────────────────────────────

STATUS_LEAD_VALIDOS = {"Nuevo", "Stand by", "Convertido", "No convertido"}

STAGE_OPP_VALIDOS = {
    "Nueva",
    "Cotización",
    "Proceso de cierre",
    "Cerrado ganado",
    "Póliza emitida",
    "Póliza no emitida",
    "Concluido",
    "Otros",
}

# Catálogos para el desglose de ramos en los KPIs (calcular_kpis).
# Prospecto y Oportunidad comparten catálogo (Ramos_de_interes__c).
RAMOS_VALIDOS = {"VIDA", "DAÑOS", "ACCIDENTES Y ENFERMEDADES"}

# Folio (Case.Sub_ramos__c) tiene su propio catálogo, más granular.
SUB_RAMOS_VALIDOS = {
    "GASTOS MÉDICOS MAYORES",
    "VIDA INDIVIDUAL",
    "VIDA GRUPO",
    "HOGAR",
    "AUTOMÓVILES",
}

# Ramo cuyo desglose granular en distribucion_ramo_emisiones no usa
# Case.Sub_ramos__c sino Case.Producto_polizas__c (VIDA no tiene subramos
# útiles, el detalle relevante para el negocio está en el producto contratado).
RAMO_CON_DESGLOSE_POR_PRODUCTO = "VIDA"

# Empresas principales para el desglose de ganancia por Account.Negocio__c
# dentro del ramo ACCIDENTES Y ENFERMEDADES. Cualquier otro valor (u
# ausente) cae en el bucket "OTROS".
EMPRESA_GRUPO_BIMBO = "GRUPO BIMBO, S.A.B. DE C.V."
EMPRESA_SINDICATO_TELEFONISTAS = "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA"
EMPRESAS_PRINCIPALES = {EMPRESA_GRUPO_BIMBO, EMPRESA_SINDICATO_TELEFONISTAS}
RAMO_CON_DESGLOSE_EMPRESA = "ACCIDENTES Y ENFERMEDADES"

# Campos SOQL para cada objeto
LEAD_FIELDS = (
    "Id, Name, Status, IsConverted, ConvertedAccountId, ConvertedOpportunityId, "
    "Negocio__c, Filial__c, No_expediente_No_colaborador__c, RFC__c, "
    "Estado_de_la_republica__c, Genero__c, Edad__c, Fecha_de_nacimiento__c, "
    "Ramos_de_interes__c, Email, MobilePhone, LeadSource, Nivel_interes__c, "
    "Presupuesto_disponible__c, Asesor_externo__c, Campana_del__c, "
    "Campana_del__r.Name, "
    "Raz_n_de_perdida__c, Impedimentos__c, Comentarios_lead_perdido__c, "
    "OwnerId, Owner.Name, CreatedById, CreatedBy.Name, "
    "LastModifiedById, LastModifiedBy.Name, CreatedDate, LastModifiedDate"
)

OPPORTUNITY_FIELDS = (
    "Id, Name, StageName, Sub_estatus__c, RecordTypeId, "
    "RecordType.Name, CampaignId, Campaign.Name, "
    "Presupuesto_disponible__c, Ramos_de_interes__c, Ramos__c, Sub_ramos__c, "
    "Nivel_interes__c, Prima_total_cotizada__c, "
    "Prima_total_emitida__c, Cotizacion__c, Fecha_de_seguimiento__c, "
    "Fecha_de_cita_agendada__c, Ciclo_de_vida__c, Duracion_en_etapa_Nueva__c, "
    "Duracion_en_etapa_Cotizacion__c, Duracion_en_etapa_Proceso_de_cierre__c, "
    "Responsable_decision__c, Tiempo_estimado__c, Impedimentos__c, "
    "Razon_de_perdida__c, Otra_razon_de_perdida__c, CloseDate, Probability, "
    "Origen_de_oportunidad__c, AccountId, Account.Name, Account.Negocio__c, "
    "CreatedDate, OwnerId, Owner.Name, LastModifiedDate, LastModifiedBy.Name"
)

CASE_FIELDS = (
    "Id, CaseNumber, Nomenclatura_campo_bandera__c, Oportunidad__c, "
    "Status, Subject, Tipo_de_movimiento__c, "
    "P_liza_de_seguro__c, P_liza_de_seguro__r.Name, "
    "P_liza_de_seguro__r.Prima_total_for__c, P_liza_de_seguro__r.Status, "
    "Poliza_emitida__c, Poliza_no_emitida__c, "
    "Razon_de_no_emision__c, "
    "Ramo__c, Sub_ramos__c, Aseguradora__c, Producto_polizas__c, "
    "CreatedDate, ClosedDate, "
    "Asesor_externo__r.Name, CreatedBy.Name, LastModifiedBy.Name, Owner.Name"
)

ACCOUNT_FIELDS = (
    "Id, Name, Negocio__c, CreatedBy.Name, CreatedDate"
)


# ─── Helpers ──────────────────────────────────────────────────────

def _limpiar_registro(record: Dict[str, Any]) -> Dict[str, Any]:
    """Elimina el atributo 'attributes' de un registro de Salesforce."""
    record = dict(record)
    record.pop("attributes", None)
    return record


def _normalizar_float(valor: Any) -> Optional[float]:
    """
    Convierte un valor de Salesforce a float, o None si no es parseable.
    Maneja strings con formato de moneda: '$200 – $400' -> None (rango no convertible).
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return None
        # Quitar símbolo de moneda y comas
        texto_limpio = texto.replace("$", "").replace(",", "").strip()
        # Si contiene un rango (ej. "$200 – $400"), no es un número único
        if "–" in texto_limpio or "-" in texto_limpio or "a" in texto_limpio.lower():
            return None
        # Si contiene < o > (ej. "<100"), no es un número único
        if "<" in texto_limpio or ">" in texto_limpio:
            return None
        try:
            return float(texto_limpio)
        except (ValueError, TypeError):
            return None
    return None


def _normalizar_int(valor: Any) -> Optional[int]:
    """Convierte un valor de Salesforce a int, o None si no es parseable."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return int(valor)
    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return None
        try:
            return int(float(texto))
        except (ValueError, TypeError):
            return None
    return None


def _normalizar_str(valor: Any) -> Optional[str]:
    """Convierte un valor de Salesforce a string, o None si es vacío."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return str(valor).lower()
    texto = str(valor).strip()
    return texto if texto else None


def _extraer_nombre_relacion(valor: Any) -> Optional[str]:
    """
    Extrae el nombre de una relación de Salesforce (Owner.Name, CreatedBy.Name, etc.).

    Salesforce devuelve las relaciones como dict anidado:
        {'Name': 'Juan Perez', 'attributes': {...}}
    o directamente como string en algunos casos.

    Args:
        valor: Valor de la relación o string directo.

    Returns:
        El nombre como string, o None si no hay valor.
    """
    if valor is None:
        return None
    if isinstance(valor, dict):
        nombre = valor.get("Name") or valor.get("name")
        return _normalizar_str(nombre)
    return _normalizar_str(valor)


def _parsear_fecha(valor: Any) -> Optional[datetime]:
    """Convierte un valor de fecha de Salesforce a datetime, o None si no es válido."""
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _fecha_en_periodo(fecha: Any, inicio: datetime, fin: datetime) -> bool:
    """Verifica si una fecha cae dentro del periodo [inicio, fin]."""
    dt = _parsear_fecha(fecha)
    if dt is None:
        return False
    return inicio <= dt <= fin


# ─── Capa 0: Resolución del asesor (User / Asesor_externo__c) ─────

def obtener_user_id_por_alias(sf: Salesforce, numero_asesor: str) -> Optional[str]:
    """
    Corrobora si el asesor tiene una cuenta de usuario (User) activa en Salesforce.

    El número de asesor corresponde al campo Alias del User.

    Args:
        sf: Instancia autenticada de Salesforce.
        numero_asesor: Número de asesor (Alias del User).

    Returns:
        El Id del User si existe un usuario activo con ese Alias, o None si no.
    """
    try:
        query = (
            "SELECT Id, Name, Alias, IsActive, Email "
            "FROM User "
            f"WHERE IsActive = True AND Alias = '{numero_asesor}'"
        )
        result = query_con_reintento(sf, query)
        if result["totalSize"] > 0:
            return result["records"][0]["Id"]
        return None
    except Exception as e:
        print(f"Error al verificar cuenta de usuario para asesor {numero_asesor}: {e}")
        return None


def obtener_nombre_asesor(sf: Salesforce, numero_asesor: str) -> Optional[str]:
    """
    Obtiene el nombre del asesor. Prioriza el User activo (Alias = numero_asesor);
    si no existe, busca en Asesor_externo__c por Numero_de_asesor__c.

    Args:
        sf: Instancia autenticada de Salesforce.
        numero_asesor: Número del asesor.

    Returns:
        Nombre del asesor, o None si no se encuentra.
    """
    try:
        query_user = (
            "SELECT Id, Name, Alias FROM User "
            f"WHERE IsActive = True AND Alias = '{numero_asesor}' "
            "ORDER BY CreatedDate DESC LIMIT 1"
        )
        result_user = query_con_reintento(sf, query_user)
        if result_user["totalSize"] > 0:
            return result_user["records"][0].get("Name")

        query_asesor = (
            "SELECT Id, Name FROM Asesor_externo__c "
            f"WHERE Numero_de_asesor__c = {numero_asesor} "
            "ORDER BY CreatedDate DESC LIMIT 1"
        )
        result_asesor = query_con_reintento(sf, query_asesor)
        if result_asesor["totalSize"] > 0:
            return result_asesor["records"][0].get("Name")
        return None
    except Exception as e:
        print(f"Error al obtener nombre del asesor {numero_asesor}: {e}")
        return None


# ─── Capa 1: Consultas a Salesforce ───────────────────────────────

def consultar_leads_por_asesor(
    sf: Salesforce,
    user_id: str,
    status_lead: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Consulta todos los Leads del asesor filtrando por OwnerId (propietario principal).

    El filtrado se hace únicamente por el OwnerId del User activo cuyo Alias
    coincide con el número de asesor, ya que el campo Asesor_externo__c
    frecuentemente no se llena.

    Args:
        sf: Instancia autenticada de Salesforce.
        user_id: Id del User activo con Alias = numero_asesor.
        status_lead: Filtro opcional por Status exacto del Lead.
        fecha_inicio: Filtro opcional CreatedDate >= fecha_inicio.
        fecha_fin: Filtro opcional CreatedDate <= fecha_fin.

    Returns:
        Lista de registros Lead.
    """
    condiciones = [f"OwnerId = '{user_id}'"]

    if status_lead:
        condiciones.append(f"Status = '{status_lead}'")

    if fecha_inicio:
        condiciones.append(f"CreatedDate >= {fecha_inicio}T00:00:00Z")

    if fecha_fin:
        condiciones.append(f"CreatedDate <= {fecha_fin}T23:59:59Z")

    where_clause = " AND ".join(condiciones)

    query = (
        f"SELECT {LEAD_FIELDS} FROM Lead "
        f"WHERE {where_clause} "
        f"ORDER BY CreatedDate DESC"
    )

    result = query_con_reintento(sf, query)
    return [_limpiar_registro(r) for r in result.get("records", [])]


def consultar_oportunidades_en_lote(
    sf: Salesforce,
    opportunity_ids: List[str],
    stage_opp: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Consulta Oportunidades en lote por lista de IDs.

    Args:
        sf: Instancia autenticada de Salesforce.
        opportunity_ids: Lista de IDs de oportunidades.
        stage_opp: Filtro opcional por StageName exacto.
        fecha_inicio: Filtro opcional CreatedDate >= fecha_inicio.
        fecha_fin: Filtro opcional CreatedDate <= fecha_fin.

    Returns:
        Dict {opportunity_id: registro de Opportunity}.
    """
    if not opportunity_ids:
        return {}

    oportunidades = {}

    # Procesar en lotes para evitar Error 414 URI Too Long
    for i in range(0, len(opportunity_ids), _MAX_IDS_POR_LOTE):
        lote_ids = opportunity_ids[i:i + _MAX_IDS_POR_LOTE]
        ids_str = ", ".join(f"'{oid}'" for oid in lote_ids)
        condiciones = [f"Id IN ({ids_str})"]

        # "Otros" no se aplica en la query porque representa etapas inactivas/rezagadas
        # que no están en el catálogo. El filtrado de "Otros" se hace en memoria.
        if stage_opp and stage_opp != "Otros":
            condiciones.append(f"StageName = '{stage_opp}'")

        if fecha_inicio:
            condiciones.append(f"CreatedDate >= {fecha_inicio}T00:00:00Z")

        if fecha_fin:
            condiciones.append(f"CreatedDate <= {fecha_fin}T23:59:59Z")

        where_clause = " AND ".join(condiciones)
        query = f"SELECT {OPPORTUNITY_FIELDS} FROM Opportunity WHERE {where_clause}"

        result = query_con_reintento(sf, query)
        for record in result.get("records", []):
            record = _limpiar_registro(record)
            oportunidades[record["Id"]] = record

    return oportunidades


def consultar_oportunidades_por_asesor(
    sf: Salesforce,
    user_id: str,
    stage_opp: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Consulta TODAS las oportunidades del asesor (no solo las de leads convertidos).

    Esto incluye oportunidades de venta directa (cross-selling, renovaciones)
    que nacieron directamente en cuentas existentes, sin pasar por Lead.

    Args:
        sf: Instancia autenticada de Salesforce.
        user_id: Id del User activo con Alias = numero_asesor.
        stage_opp: Filtro opcional por StageName exacto.
        fecha_inicio: Filtro opcional CreatedDate >= fecha_inicio.
        fecha_fin: Filtro opcional CreatedDate <= fecha_fin.

    Returns:
        Dict {opportunity_id: registro de Opportunity}.
    """
    condiciones = [f"OwnerId = '{user_id}'"]

    # "Otros" no se aplica en la query porque representa etapas inactivas/rezagadas
    # que no están en el catálogo. El filtrado de "Otros" se hace en memoria.
    if stage_opp and stage_opp != "Otros":
        condiciones.append(f"StageName = '{stage_opp}'")

    if fecha_inicio:
        condiciones.append(f"CreatedDate >= {fecha_inicio}T00:00:00Z")

    if fecha_fin:
        condiciones.append(f"CreatedDate <= {fecha_fin}T23:59:59Z")

    where_clause = " AND ".join(condiciones)
    query = f"SELECT {OPPORTUNITY_FIELDS} FROM Opportunity WHERE {where_clause} ORDER BY CreatedDate DESC"

    result = query_con_reintento(sf, query)
    oportunidades = {}
    for record in result.get("records", []):
        record = _limpiar_registro(record)
        oportunidades[record["Id"]] = record
    return oportunidades


# Tamaño máximo de IDs por consulta SOQL (evita Error 414 URI Too Long)
_MAX_IDS_POR_LOTE = 200


def consultar_folios_en_lote(
    sf: Salesforce,
    opportunity_ids: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Consulta Folios (Case) en lote por lista de IDs de oportunidades.

    Los folios se vinculan a la oportunidad mediante el campo Oportunidad__c.
    Si hay muchos IDs, se divide la consulta en lotes para evitar
    "Error 414 URI Too Long".

    Args:
        sf: Instancia autenticada de Salesforce.
        opportunity_ids: Lista de IDs de oportunidades.

    Returns:
        Dict {opportunity_id: lista de registros de Case}.
    """
    if not opportunity_ids:
        return {}

    folios_por_opp: Dict[str, List[Dict[str, Any]]] = {}

    # Procesar en lotes para evitar URI demasiado larga
    for i in range(0, len(opportunity_ids), _MAX_IDS_POR_LOTE):
        lote_ids = opportunity_ids[i:i + _MAX_IDS_POR_LOTE]
        ids_str = ", ".join(f"'{oid}'" for oid in lote_ids)
        query = (
            f"SELECT {CASE_FIELDS} FROM Case "
            f"WHERE Oportunidad__c IN ({ids_str})"
        )

        result = query_con_reintento(sf, query)
        for record in result.get("records", []):
            record = _limpiar_registro(record)
            opp_id = record.get("Oportunidad__c")
            if opp_id:
                folios_por_opp.setdefault(opp_id, []).append(record)

    return folios_por_opp


def consultar_cuentas_en_lote(
    sf: Salesforce,
    account_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """
    Consulta Cuentas (Account) en lote por lista de IDs.

    Si hay muchos IDs, se divide la consulta en lotes para evitar
    "Error 414 URI Too Long".

    Args:
        sf: Instancia autenticada de Salesforce.
        account_ids: Lista de IDs de cuentas convertidas.

    Returns:
        Dict {account_id: registro de Account}.
    """
    if not account_ids:
        return {}

    cuentas = {}

    # Procesar en lotes para evitar Error 414 URI Too Long
    for i in range(0, len(account_ids), _MAX_IDS_POR_LOTE):
        lote_ids = account_ids[i:i + _MAX_IDS_POR_LOTE]
        ids_str = ", ".join(f"'{aid}'" for aid in lote_ids)
        query = (
            f"SELECT {ACCOUNT_FIELDS} FROM Account "
            f"WHERE Id IN ({ids_str})"
        )

        result = query_con_reintento(sf, query)
        for record in result.get("records", []):
            record = _limpiar_registro(record)
            cuentas[record["Id"]] = record

    return cuentas


# ─── Capa 2: Mapeo de registros ───────────────────────────────────

def mapear_prospecto(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Mapea un registro de Lead a la estructura ProspectoInfo."""
    return {
        "lead_id": lead.get("Id"),
        "name": _normalizar_str(lead.get("Name")),
        "status": _normalizar_str(lead.get("Status")),
        "is_converted": bool(lead.get("IsConverted", False)),
        "negocio": _normalizar_str(lead.get("Negocio__c")),
        "filial": _normalizar_str(lead.get("Filial__c")),
        "no_expediente_no_colaborador": _normalizar_str(lead.get("No_expediente_No_colaborador__c")),
        "rfc": _normalizar_str(lead.get("RFC__c")),
        "estado_republica": _normalizar_str(lead.get("Estado_de_la_republica__c")),
        "genero": _normalizar_str(lead.get("Genero__c")),
        "edad": _normalizar_int(lead.get("Edad__c")),
        "fecha_nacimiento": _normalizar_str(lead.get("Fecha_de_nacimiento__c")),
        "ramos_interes": _normalizar_str(lead.get("Ramos_de_interes__c")),
        "email": _normalizar_str(lead.get("Email")),
        "mobile_phone": _normalizar_str(lead.get("MobilePhone")),
        "lead_source": _normalizar_str(lead.get("LeadSource")),
        "nivel_interes": _normalizar_str(lead.get("Nivel_interes__c")),
        "presupuesto_disponible": _normalizar_float(lead.get("Presupuesto_disponible__c")),
        "campana_del": _extraer_nombre_relacion(lead.get("Campana_del__r")) or _normalizar_str(lead.get("Campana_del__c")),
        "razon_perdida": _normalizar_str(lead.get("Raz_n_de_perdida__c")),
        "impedimentos": _normalizar_str(lead.get("Impedimentos__c")),
        "comentarios_lead_perdido": _normalizar_str(lead.get("Comentarios_lead_perdido__c")),
        "owner_name": _extraer_nombre_relacion(lead.get("Owner")),
        "created_by_name": _extraer_nombre_relacion(lead.get("CreatedBy")),
        "last_modified_by_name": _extraer_nombre_relacion(lead.get("LastModifiedBy")),
        "created_date": _normalizar_str(lead.get("CreatedDate")),
        "last_modified_date": _normalizar_str(lead.get("LastModifiedDate")),
    }


def mapear_cuenta(
    lead: Dict[str, Any],
    cuentas: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Mapea la cuenta convertida desde el Lead, o None si no fue convertido."""
    account_id = lead.get("ConvertedAccountId")
    if not account_id:
        return None

    account = cuentas.get(account_id, {})
    return {
        "account_id": account_id,
        "account_name": _normalizar_str(account.get("Name") or lead.get("Name")),
        "negocio": _normalizar_str(account.get("Negocio__c")),
        "created_by_name": _extraer_nombre_relacion(account.get("CreatedBy")),
        "created_date": _normalizar_str(account.get("CreatedDate")),
    }


def mapear_oportunidad(opp: Dict[str, Any]) -> Dict[str, Any]:
    """Mapea un registro de Opportunity a la estructura OportunidadInfo."""
    return {
        "opportunity_id": opp.get("Id"),
        "name": _normalizar_str(opp.get("Name")),
        "stage_name": _normalizar_str(opp.get("StageName")),
        "sub_estatus": _normalizar_str(opp.get("Sub_estatus__c")),
        "record_type_name": _extraer_nombre_relacion(opp.get("RecordType")),
        "campaign_name": _extraer_nombre_relacion(opp.get("Campaign")),
        "presupuesto_disponible": _normalizar_float(opp.get("Presupuesto_disponible__c")),
        "ramos_interes": _normalizar_str(opp.get("Ramos_de_interes__c")),
        "nivel_interes": _normalizar_str(opp.get("Nivel_interes__c")),
        "owner_name": _extraer_nombre_relacion(opp.get("Owner")),
        "origen_oportunidad": _normalizar_str(opp.get("Origen_de_oportunidad__c")),
        "close_date": _normalizar_str(opp.get("CloseDate")),
        "probability": _normalizar_int(opp.get("Probability")),
        "fecha_seguimiento": _normalizar_str(opp.get("Fecha_de_seguimiento__c")),
        "fecha_cita_agendada": _normalizar_str(opp.get("Fecha_de_cita_agendada__c")),
        "ciclo_de_vida": _normalizar_str(opp.get("Ciclo_de_vida__c")),
        "duracion_etapas": {
            "nueva_dias": _normalizar_int(opp.get("Duracion_en_etapa_Nueva__c")),
            "cotizacion_dias": _normalizar_int(opp.get("Duracion_en_etapa_Cotizacion__c")),
            "proceso_cierre_dias": _normalizar_int(opp.get("Duracion_en_etapa_Proceso_de_cierre__c")),
        },
        "responsable_decision": _normalizar_str(opp.get("Responsable_decision__c")),
        "tiempo_estimado": _normalizar_str(opp.get("Tiempo_estimado__c")),
        "impedimentos": _normalizar_str(opp.get("Impedimentos__c")),
        "ramos": _normalizar_str(opp.get("Ramos__c")),
        "sub_ramos": _normalizar_str(opp.get("Sub_ramos__c")),
        "prima_total_cotizada": _normalizar_float(opp.get("Prima_total_cotizada__c")),
        "prima_total_emitida": _normalizar_float(opp.get("Prima_total_emitida__c")),
        "cotizacion": _normalizar_str(opp.get("Cotizacion__c")),
        "razon_perdida": _normalizar_str(opp.get("Razon_de_perdida__c")),
        "otra_razon_perdida": _normalizar_str(opp.get("Otra_razon_de_perdida__c")),
        "created_date": _normalizar_str(opp.get("CreatedDate")),
        "last_modified_date": _normalizar_str(opp.get("LastModifiedDate")),
        "last_modified_by_name": _extraer_nombre_relacion(opp.get("LastModifiedBy")),
    }


def mapear_folio(folio: Dict[str, Any]) -> Dict[str, Any]:
    """Mapea un registro de Case a la estructura FolioEmisionInfo."""
    return {
        "case_id": folio.get("Id"),
        "case_number": _normalizar_str(folio.get("CaseNumber")),
        "nomenclatura": _normalizar_str(folio.get("Nomenclatura_campo_bandera__c")),
        "status": _normalizar_str(folio.get("Status")),
        "subject": _normalizar_str(folio.get("Subject")),
        "tipo_movimiento": _normalizar_str(folio.get("Tipo_de_movimiento__c")),
        "razon_no_emision": _normalizar_str(folio.get("Razon_de_no_emision__c")),
        "ramo": _normalizar_str(folio.get("Ramo__c")),
        "sub_ramos": _normalizar_str(folio.get("Sub_ramos__c")),
        "aseguradora": _normalizar_str(folio.get("Aseguradora__c")),
        "producto_polizas": _normalizar_str(folio.get("Producto_polizas__c")),
        "poliza_name": _extraer_nombre_relacion(folio.get("P_liza_de_seguro__r")) or _normalizar_str(folio.get("P_liza_de_seguro__c")),
        "poliza_prima_total": _normalizar_float((folio.get("P_liza_de_seguro__r") or {}).get("Prima_total_for__c")),
        "poliza_status": _normalizar_str((folio.get("P_liza_de_seguro__r") or {}).get("Status")),
        "poliza_emitida": bool(folio.get("Poliza_emitida__c", False)),
        "poliza_no_emitida": bool(folio.get("Poliza_no_emitida__c", False)),
        "created_date": _normalizar_str(folio.get("CreatedDate")),
        "closed_date": _normalizar_str(folio.get("ClosedDate")),
        "asesor_externo_name": _extraer_nombre_relacion(folio.get("Asesor_externo__r")),
        "created_by_name": _extraer_nombre_relacion(folio.get("CreatedBy")),
        "last_modified_by_name": _extraer_nombre_relacion(folio.get("LastModifiedBy")),
        "owner_name": _extraer_nombre_relacion(folio.get("Owner")),
    }


# ─── Capa 3: Ensamblado de items ──────────────────────────────────

def construir_items(
    leads: List[Dict[str, Any]],
    oportunidades: Dict[str, Dict[str, Any]],
    folios_por_opp: Dict[str, List[Dict[str, Any]]],
    cuentas: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Ensambla la matriz de trazabilidad aplanada a partir de los resultados.

    Args:
        leads: Lista de registros Lead.
        oportunidades: Dict {opp_id: registro Opportunity}.
        folios_por_opp: Dict {opp_id: lista de Case}.
        cuentas: Dict {account_id: registro Account}.

    Returns:
        Lista de items de seguimiento.
    """
    items = []
    for idx, lead in enumerate(leads, start=1):
        opp_id = lead.get("ConvertedOpportunityId")
        opp = oportunidades.get(opp_id) if opp_id else None

        folios = []
        if opp_id:
            for folio in folios_por_opp.get(opp_id, []):
                folios.append(mapear_folio(folio))

        # Clasificar origen del registro
        if opp and lead.get("IsConverted"):
            origen = "PROSPECTO_CONVERTIDO"
        elif opp and not lead.get("IsConverted"):
            origen = "VENTA_DIRECTA_CUENTA"
        else:
            origen = "PROSPECTO_NO_CONVERTIDO"

        items.append({
            "seguimiento_id": f"TRC-{idx:03d}",
            "origen_registro": origen,
            "prospecto": mapear_prospecto(lead),
            "cuenta": mapear_cuenta(lead, cuentas),
            "oportunidad": mapear_oportunidad(opp) if opp else None,
            "folios_emision": folios,
        })
    return items


def construir_items_unificada(
    leads: List[Dict[str, Any]],
    oportunidades: Dict[str, Dict[str, Any]],
    folios_por_opp: Dict[str, List[Dict[str, Any]]],
    cuentas: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Ensambla la matriz unificada de trazabilidad con clasificación de 3 escenarios.

    Escenarios:
    A: PROSPECTO_CONVERTIDO - Lead convertido con oportunidad asociada
    B: VENTA_DIRECTA_CUENTA - Oportunidad directa en cuenta (sin Lead)
    C: PROSPECTO_NO_CONVERTIDO - Lead no convertido sin oportunidad

    Args:
        leads: Lista de registros Lead.
        oportunidades: Dict {opp_id: registro Opportunity}.
        folios_por_opp: Dict {opp_id: lista de Case}.
        cuentas: Dict {account_id: registro Account}.

    Returns:
        Lista de items de seguimiento con origen_registro.
    """
    items = []

    # Build lookup: opportunity_id -> lead convertido
    leads_por_opp: Dict[str, Dict] = {}
    leads_no_convertidos = []

    for lead in leads:
        if lead.get("IsConverted"):
            opp_id = lead.get("ConvertedOpportunityId")
            if opp_id:
                leads_por_opp[opp_id] = lead
        else:
            leads_no_convertidos.append(lead)

    # Para cada oportunidad, clasificar escenario
    for opp_id, opp in oportunidades.items():
        lead_convertido = leads_por_opp.get(opp_id)

        # Asociar folios
        folios = folios_por_opp.get(opp_id, [])
        folios_mapeados = [mapear_folio(f) for f in folios] if folios else []

        if lead_convertido:
            # Escenario A: Prospecto Convertido
            origen = "PROSPECTO_CONVERTIDO"
            prospecto_map = mapear_prospecto(lead_convertido)
            cuenta_map = mapear_cuenta(lead_convertido, cuentas)
        else:
            # Escenario B: Venta Directa en Cuenta
            origen = "VENTA_DIRECTA_CUENTA"
            prospecto_map = None
            # Cuenta viene directamente de la oportunidad
            account_id = opp.get("AccountId")
            account_name = None
            negocio = None
            if opp.get("Account") and isinstance(opp.get("Account"), dict):
                account_name = _normalizar_str(opp.get("Account").get("Name"))
                negocio = _normalizar_str(opp.get("Account").get("Negocio__c"))
            if account_id:
                cuenta_map = {
                    "account_id": account_id,
                    "account_name": account_name,
                    "negocio": negocio,
                }
            else:
                cuenta_map = None

        items.append({
            "seguimiento_id": f"TRC-{len(items) + 1:03d}",
            "origen_registro": origen,
            "prospecto": prospecto_map,
            "cuenta": cuenta_map,
            "oportunidad": mapear_oportunidad(opp),
            "folios_emision": folios_mapeados,
        })

    # Escenario C: Prospectos No Convertidos (sin oportunidad)
    for lead_nc in leads_no_convertidos:
        items.append({
            "seguimiento_id": f"TRC-{len(items) + 1:03d}",
            "origen_registro": "PROSPECTO_NO_CONVERTIDO",
            "prospecto": mapear_prospecto(lead_nc),
            "cuenta": None,
            "oportunidad": None,
            "folios_emision": [],
        })

    return items


# ─── Capa 4: KPIs ─────────────────────────────────────────────────

def calcular_kpis(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calcula métricas agregadas (KPIs) sobre los items de seguimiento.

    Args:
        items: Lista de items de seguimiento.

    Returns:
        Dict con los KPIs totales.
    """
    total_prospectos = 0
    nuevos = 0
    stand_by = 0
    convertidos = 0
    no_convertidos = 0
    total_oportunidades = 0
    etapa_nueva = 0
    etapa_cotizacion = 0
    etapa_proceso_cierre = 0
    cerrado_ganado = 0
    poliza_emitida = 0
    poliza_no_emitida = 0
    concluido = 0
    otros = 0
    total_folios = 0
    monto_cotizado = 0.0
    monto_emitido = 0.0

    # Contadores de folios
    folios_emitidos = 0
    folios_no_emitidos = 0
    folios_en_proceso = 0
    polizas_canceladas = 0
    polizas_vigentes = 0

    # KPIs nuevos para Fase 4.0
    oportunidades_origen_prospecto = 0
    oportunidades_origen_cuenta_existente = 0

    # Desglose por ramo (Ramos_de_interes__c en prospecto/oportunidad,
    # Ramo__c y Sub_ramos__c en folio). Como no existen valores fuera de
    # estos catálogos, lo que cae aquí es un campo vacío/no capturado —
    # justo lo que se quiere medir: quién no está trazando bien el dato.
    ramos_prospectos = {ramo: 0 for ramo in RAMOS_VALIDOS}
    ramos_prospectos["sin_ramo"] = 0
    ramos_oportunidades = {ramo: 0 for ramo in RAMOS_VALIDOS}
    ramos_oportunidades["sin_ramo"] = 0
    ramos_folios = {ramo: 0 for ramo in RAMOS_VALIDOS}
    ramos_folios["sin_ramo"] = 0
    sub_ramos_folios = {sub_ramo: 0 for sub_ramo in SUB_RAMOS_VALIDOS}
    sub_ramos_folios["sin_sub_ramo"] = 0

    for item in items:
        # ── Conteo de prospectos (solo items con prospecto) ──────
        prospecto = item.get("prospecto")
        if prospecto is not None:
            total_prospectos += 1
            status = (prospecto.get("status") or "").strip().lower()

            if prospecto.get("is_converted"):
                convertidos += 1
            elif status == "nuevo":
                nuevos += 1
            elif status == "stand by":
                stand_by += 1
            else:
                no_convertidos += 1

            ramo_prospecto = prospecto.get("ramos_interes")
            if ramo_prospecto in ramos_prospectos:
                ramos_prospectos[ramo_prospecto] += 1
            else:
                ramos_prospectos["sin_ramo"] += 1

        # ── Conteo de oportunidades (todos los items con opp) ────
        opp = item.get("oportunidad")
        if opp:
            total_oportunidades += 1
            stage = (opp.get("stage_name") or "").strip().lower()
            if stage == "nueva":
                etapa_nueva += 1
            elif stage == "cotización" or stage == "cotizacion":
                etapa_cotizacion += 1
            elif stage == "proceso de cierre":
                etapa_proceso_cierre += 1
            elif stage == "cerrado ganado":
                cerrado_ganado += 1
            elif stage == "póliza emitida":
                poliza_emitida += 1
            elif stage == "póliza no emitida":
                poliza_no_emitida += 1
            elif stage == "concluido":
                concluido += 1
            else:
                otros += 1

            ramo_opp = opp.get("ramos_interes")
            if ramo_opp in ramos_oportunidades:
                ramos_oportunidades[ramo_opp] += 1
            else:
                ramos_oportunidades["sin_ramo"] += 1

            prima_cotizada = opp.get("prima_total_cotizada") or 0.0
            prima_emitida = opp.get("prima_total_emitida") or 0.0
            monto_cotizado += prima_cotizada
            monto_emitido += prima_emitida

            # KPIs nuevos: clasificar origen de la oportunidad
            origen = item.get("origen_registro")
            if origen == "PROSPECTO_CONVERTIDO":
                oportunidades_origen_prospecto += 1

        # ── Contar folios por estado ─────────────────────────────
        for folio in item.get("folios_emision", []):
            total_folios += 1

            ramo_folio = folio.get("ramo")
            if ramo_folio in ramos_folios:
                ramos_folios[ramo_folio] += 1
            else:
                ramos_folios["sin_ramo"] += 1

            sub_ramo_folio = folio.get("sub_ramos")
            if sub_ramo_folio in sub_ramos_folios:
                sub_ramos_folios[sub_ramo_folio] += 1
            else:
                sub_ramos_folios["sin_sub_ramo"] += 1

            if folio.get("poliza_emitida"):
                folios_emitidos += 1

                # ── Contar pólizas por status (Cancelado / Vigente) ───
                # Solo entre folios emitidos: un folio aún en proceso puede
                # traer una póliza ya existente/activa referenciada (no una
                # que él mismo emitió), y no debe contarse aquí.
                poliza_status = (folio.get("poliza_status") or "").strip().lower()
                if poliza_status == "cancelado":
                    polizas_canceladas += 1
                elif poliza_status == "vigente":
                    polizas_vigentes += 1
            elif folio.get("poliza_no_emitida"):
                folios_no_emitidos += 1
            else:
                folios_en_proceso += 1

    return {
        "resumen_ejecutivo": {
            "totales_embudo": {
                "total_prospectos": total_prospectos,
                "total_oportunidades": total_oportunidades,
                "total_polizas_emitidas": folios_emitidos,
                "total_canceladas": polizas_canceladas,
                "total_vigente": polizas_vigentes,
            },
            "metrica_financiera": {
                "monto_total_cotizado": round(monto_cotizado, 2),
                "monto_total_emitido": round(monto_emitido, 2),
            },
            "total_registros_seguimiento": len(items),
        },
        "detalle_prospeccion": {
            "convertidos": convertidos,
            "no_convertidos": no_convertidos,
            "stand_by": stand_by,
            "nuevos": nuevos,
        },
        "detalle_oportunidades": {
            "origen": {
                "prospectos": oportunidades_origen_prospecto,
                "cuentas_existentes": total_oportunidades - oportunidades_origen_prospecto,
            },
            "etapas": {
                "nueva": etapa_nueva,
                "cotizacion": etapa_cotizacion,
                "proceso_cierre": etapa_proceso_cierre,
                "cerrado_ganado": cerrado_ganado,
                "poliza_emitida": poliza_emitida,
                "poliza_no_emitida": poliza_no_emitida,
                "concluido": concluido,
                "otros": otros,
            },
        },
        "detalle_folios_tramite": {
            "total_folios": total_folios,
            "emitidos": folios_emitidos,
            "en_proceso": folios_en_proceso,
            "no_emitidos": folios_no_emitidos,
        },
        "detalle_ramos": {
            "prospectos": ramos_prospectos,
            "oportunidades": ramos_oportunidades,
            "folios": {
                "ramo": ramos_folios,
                "sub_ramo": sub_ramos_folios,
            },
        },
    }


# ─── Capa 4.5: Producción del periodo vs. cohorte de creación ─────
#
# Distinción de negocio (Ajuste Técnico 2026-08-31):
# - "Producción del periodo" = folios EMITIDOS cuyo Case.ClosedDate cae en
#   el rango, sin importar cuándo se creó la Oportunidad que los originó
#   (incluye "arrastre": oportunidades viejas cerradas este periodo).
# - "Cohorte de creación" = Leads/Oportunidades cuyo propio CreatedDate
#   cae en el rango, y cómo les fue (emitida en el mismo periodo, en
#   proceso, o no emitida).
#
# Estos campos son ADITIVOS: conviven con resumen_ejecutivo/detalle_* de
# calcular_kpis sin reemplazarlos ni modificarlos.

def _clave_sub_ramo(ramo: str, folio: Dict[str, Any]) -> str:
    """
    Clave del desglose granular dentro de un ramo. VIDA se agrupa por
    Producto_polizas__c (Case.producto_polizas) porque su Sub_ramos__c no es
    útil para el negocio; el resto de los ramos usa Sub_ramos__c.
    """
    if ramo == RAMO_CON_DESGLOSE_POR_PRODUCTO:
        valor = folio.get("producto_polizas")
    else:
        valor = folio.get("sub_ramos")
    return valor or "SIN_SUB_RAMO"


def _clasificar_empresa(cuenta: Optional[Dict[str, Any]]) -> str:
    """Clasifica Account.Negocio__c en una de las dos empresas principales, u 'OTROS'."""
    negocio = (cuenta or {}).get("negocio")
    return negocio if negocio in EMPRESAS_PRINCIPALES else "OTROS"


def _bucket_vacio() -> Dict[str, Any]:
    """Acumulador crudo de un bucket (ramo / sub_ramo / empresa): monto y
    conteo de pólizas emitidas, partidos por mismo_periodo vs. arrastre_pasado."""
    return {
        "monto": 0.0,
        "monto_mismo_periodo": 0.0,
        "monto_arrastre_pasado": 0.0,
        "count": 0,
        "count_mismo_periodo": 0,
        "count_arrastre_pasado": 0,
    }


def _acumular_bucket(buckets: Dict[str, Dict[str, Any]], clave: str, monto: float, mismo_periodo: bool) -> None:
    """Suma una póliza emitida al bucket `clave` dentro de `buckets` (se crea si no existe)."""
    bucket = buckets.setdefault(clave, _bucket_vacio())
    bucket["monto"] += monto
    bucket["count"] += 1
    if mismo_periodo:
        bucket["monto_mismo_periodo"] += monto
        bucket["count_mismo_periodo"] += 1
    else:
        bucket["monto_arrastre_pasado"] += monto
        bucket["count_arrastre_pasado"] += 1


def _sumar_bucket(destino: Dict[str, Any], entry: Dict[str, Any]) -> None:
    """Suma los valores crudos de una entrada ya construida (de un asesor) dentro de un bucket agregado global."""
    destino["monto"] += entry.get("prima_total") or 0.0
    destino["monto_mismo_periodo"] += entry.get("prima_mismo_periodo") or 0.0
    destino["monto_arrastre_pasado"] += entry.get("prima_arrastre_pasado") or 0.0
    destino["count"] += entry.get("emitidas") or 0
    destino["count_mismo_periodo"] += entry.get("emitidas_mismo_periodo") or 0
    destino["count_arrastre_pasado"] += entry.get("emitidas_arrastre_pasado") or 0


def _construir_bucket_entry(
    campo_nombre: str,
    nombre: str,
    bucket: Dict[str, Any],
    monto_ref: float,
    count_ref: int,
) -> Dict[str, Any]:
    """
    Construye una entrada de desglose ({ramo|sub_ramo|empresa, monto, porcentaje,
    emitidas, ...}) a partir de un bucket crudo. `monto_ref`/`count_ref` son la
    base contra la que se calculan los porcentajes: el total general para las
    entradas de nivel ramo, o el monto/conteo del ramo padre para los desgloses
    anidados (sub_ramo/empresa) — así cada desglose refleja su composición
    interna, no su peso contra el total general.
    """
    monto = bucket["monto"]
    count = bucket["count"]
    return {
        campo_nombre: nombre,
        "monto": round(monto, 2),
        "porcentaje": round(monto / monto_ref * 100, 2) if monto_ref else 0.0,
        "emitidas": count,
        "porcentaje_emitidas": round(count / count_ref * 100, 2) if count_ref else 0.0,
        "emitidas_mismo_periodo": bucket["count_mismo_periodo"],
        "emitidas_arrastre_pasado": bucket["count_arrastre_pasado"],
        "prima_mismo_periodo": round(bucket["monto_mismo_periodo"], 2),
        "prima_arrastre_pasado": round(bucket["monto_arrastre_pasado"], 2),
        "prima_total": round(monto, 2),
    }


def construir_distribucion_ramo_emisiones(
    stats_ramo: Dict[str, Dict[str, Any]],
    stats_ramo_sub: Dict[str, Dict[str, Dict[str, Any]]],
    stats_empresa_accidentes: Dict[str, Dict[str, Any]],
    prima_colocada_total: float,
    polizas_emitidas_total: int,
) -> List[Dict[str, Any]]:
    """
    Ensambla distribucion_ramo_emisiones con su desglose anidado:
    - distribucion_sub_ramo: siempre, por Sub_ramos__c (o Producto_polizas__c en VIDA).
    - distribucion_empresa: solo en RAMO_CON_DESGLOSE_EMPRESA, por Account.Negocio__c.

    Cada entrada (ramo, y dentro de cada una sub_ramo/empresa) trae monto +
    conteo de pólizas emitidas, ambos partidos por mismo_periodo/arrastre_pasado.
    Los porcentajes de los desgloses anidados son relativos al monto/conteo
    del ramo padre (no al total general), para reflejar su composición interna;
    los de nivel ramo son relativos al total general.
    """
    distribucion = []
    for ramo, stats in stats_ramo.items():
        entry = _construir_bucket_entry("ramo", ramo, stats, prima_colocada_total, polizas_emitidas_total)
        entry["distribucion_sub_ramo"] = [
            _construir_bucket_entry("sub_ramo", sub_ramo, sub_stats, stats["monto"], stats["count"])
            for sub_ramo, sub_stats in stats_ramo_sub.get(ramo, {}).items()
        ]
        entry["distribucion_empresa"] = []
        if ramo == RAMO_CON_DESGLOSE_EMPRESA:
            entry["distribucion_empresa"] = [
                _construir_bucket_entry("empresa", empresa, emp_stats, stats["monto"], stats["count"])
                for empresa, emp_stats in stats_empresa_accidentes.items()
            ]
        distribucion.append(entry)
    return distribucion


def agregar_distribucion_ramo_emisiones(
    distribuciones_por_asesor: List[List[Dict[str, Any]]],
    prima_colocada_total: float,
    polizas_emitidas_total: int,
) -> List[Dict[str, Any]]:
    """
    Re-agrega distribucion_ramo_emisiones (incluyendo sub_ramo y empresa) de
    varios asesores en un solo total global, sumando los valores crudos de
    cada entrada y recalculando porcentajes (nunca promediando porcentajes ya
    redondeados).
    """
    stats_ramo = {r: _bucket_vacio() for r in RAMOS_VALIDOS}
    stats_ramo_sub: Dict[str, Dict[str, Dict[str, Any]]] = {r: {} for r in RAMOS_VALIDOS}
    stats_empresa_accidentes: Dict[str, Dict[str, Any]] = {}

    for distribucion in distribuciones_por_asesor:
        for entry in distribucion:
            ramo = entry.get("ramo")
            if ramo not in stats_ramo:
                continue
            _sumar_bucket(stats_ramo[ramo], entry)
            for sub in entry.get("distribucion_sub_ramo", []):
                clave = sub.get("sub_ramo")
                _sumar_bucket(stats_ramo_sub[ramo].setdefault(clave, _bucket_vacio()), sub)
            if ramo == RAMO_CON_DESGLOSE_EMPRESA:
                for emp in entry.get("distribucion_empresa", []):
                    clave = emp.get("empresa")
                    _sumar_bucket(stats_empresa_accidentes.setdefault(clave, _bucket_vacio()), emp)

    return construir_distribucion_ramo_emisiones(
        stats_ramo, stats_ramo_sub, stats_empresa_accidentes, prima_colocada_total, polizas_emitidas_total,
    )


def _resolver_rango_produccion(
    fecha_inicio: Optional[str],
    fecha_fin: Optional[str],
    periodo: Optional[str],
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """fecha_inicio/fecha_fin tienen prioridad; si no vienen, se usa periodo (YYYY-MM[:YYYY-MM])."""
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

    if periodo:
        rango = _parsear_periodo(periodo)
        if rango:
            return rango

    return None, None


def calcular_produccion_periodo(
    sf: Salesforce,
    user_id: str,
    fecha_inicio: Optional[str],
    fecha_fin: Optional[str],
    periodo: Optional[str],
) -> Dict[str, Any]:
    """
    Producción real del periodo: folios emitidos cuyo Case.ClosedDate cae
    en el rango, incluyendo "arrastre" (oportunidades creadas antes del
    rango pero cerradas dentro de él).

    Requiere una consulta adicional propia porque
    consultar_oportunidades_por_asesor/consultar_oportunidades_en_lote
    (las que ya usa el flujo principal) acotan por CreatedDate, así que
    nunca traen una oportunidad vieja cuyo folio se cerró recientemente.
    No modifica ni reutiliza el resultado de esas consultas.

    Nota: a diferencia de resumen_ejecutivo/detalle_*, este cálculo no
    aplica los filtros status_lead/stage_opp/ramo/con_folio — refleja
    toda la producción cerrada del asesor en el rango.
    """
    query_opps = f"SELECT {OPPORTUNITY_FIELDS} FROM Opportunity WHERE OwnerId = '{user_id}'"
    result_opps = query_con_reintento(sf, query_opps)
    oportunidades = {r["Id"]: _limpiar_registro(r) for r in result_opps.get("records", [])}

    opp_ids = list(oportunidades.keys())
    folios_por_opp = consultar_folios_en_lote(sf, opp_ids)

    # En lotes de _MAX_IDS_POR_LOTE para evitar "Error 431 Request Header
    # Fields Too Large" (URL de Salesforce demasiado larga con muchos Ids),
    # el mismo problema ya resuelto en consultar_oportunidades_en_lote /
    # consultar_folios_en_lote / consultar_cuentas_en_lote.
    leads = []
    for i in range(0, len(opp_ids), _MAX_IDS_POR_LOTE):
        lote_ids = opp_ids[i:i + _MAX_IDS_POR_LOTE]
        ids_str = "', '".join(lote_ids)
        query_leads = (
            f"SELECT {LEAD_FIELDS} FROM Lead "
            f"WHERE ConvertedOpportunityId IN ('{ids_str}')"
        )
        result_leads = query_con_reintento(sf, query_leads)
        leads.extend(_limpiar_registro(r) for r in result_leads.get("records", []))

    items = construir_items_unificada(leads, oportunidades, folios_por_opp, {})

    inicio, fin = _resolver_rango_produccion(fecha_inicio, fecha_fin, periodo)

    polizas_emitidas_total = 0
    prima_colocada_total = 0.0
    total_canceladas = 0
    total_vigentes = 0
    dias_emision = []
    stats_ramo = {r: _bucket_vacio() for r in RAMOS_VALIDOS}
    stats_ramo_sub: Dict[str, Dict[str, Dict[str, Any]]] = {r: {} for r in RAMOS_VALIDOS}
    stats_empresa_accidentes: Dict[str, Dict[str, Any]] = {}
    prospectos_nuevos = 0
    cuentas_existentes = 0
    emisiones_mismo_periodo = 0
    emisiones_arrastre_pasado = 0

    for item in items:
        opp = item.get("oportunidad")
        prospecto = item.get("prospecto")
        cuenta = item.get("cuenta")
        origen_registro = item.get("origen_registro")
        fecha_origen = None
        if origen_registro == "PROSPECTO_CONVERTIDO" and prospecto:
            fecha_origen = _parsear_fecha(prospecto.get("created_date"))
        elif opp:
            fecha_origen = _parsear_fecha(opp.get("created_date"))

        opp_creada_en_rango = False
        if fecha_origen:
            opp_creada_en_rango = not ((inicio and fecha_origen < inicio) or (fin and fecha_origen > fin))

        for folio in item.get("folios_emision", []):
            if not folio.get("poliza_emitida"):
                continue

            fecha_cierre = _parsear_fecha(folio.get("closed_date"))
            if fecha_cierre is None:
                continue
            if inicio and fecha_cierre < inicio:
                continue
            if fin and fecha_cierre > fin:
                continue

            polizas_emitidas_total += 1
            monto = folio.get("poliza_prima_total") or 0.0
            prima_colocada_total += monto

            ramo = folio.get("ramo")
            if ramo in stats_ramo:
                _acumular_bucket(stats_ramo, ramo, monto, opp_creada_en_rango)

                sub_ramo = _clave_sub_ramo(ramo, folio)
                _acumular_bucket(stats_ramo_sub[ramo], sub_ramo, monto, opp_creada_en_rango)

                if ramo == RAMO_CON_DESGLOSE_EMPRESA:
                    empresa = _clasificar_empresa(cuenta)
                    _acumular_bucket(stats_empresa_accidentes, empresa, monto, opp_creada_en_rango)

            status = (folio.get("poliza_status") or "").strip().lower()
            if status == "cancelado":
                total_canceladas += 1
            elif status == "vigente":
                total_vigentes += 1

            # Composición por origen del registro (Lead vs. Cuenta existente).
            if origen_registro == "PROSPECTO_CONVERTIDO":
                prospectos_nuevos += 1
            else:
                cuentas_existentes += 1

            # Composición por inmediatez: la oportunidad nació en el mismo
            # rango que se está consultando, o viene de un periodo pasado.
            if opp_creada_en_rango:
                emisiones_mismo_periodo += 1
            else:
                emisiones_arrastre_pasado += 1

            if fecha_origen and fecha_cierre:
                dias = (fecha_cierre - fecha_origen).days
                if dias >= 0:
                    dias_emision.append(dias)

    dias_promedio_emision = round(sum(dias_emision) / len(dias_emision), 1) if dias_emision else None
    ticket_promedio_prima = (
        round(prima_colocada_total / polizas_emitidas_total, 2) if polizas_emitidas_total else 0.0
    )

    distribucion_ramo_emisiones = construir_distribucion_ramo_emisiones(
        stats_ramo, stats_ramo_sub, stats_empresa_accidentes, prima_colocada_total, polizas_emitidas_total,
    )

    return {
        "polizas_emitidas_total": polizas_emitidas_total,
        "prima_colocada_total": round(prima_colocada_total, 2),
        "dias_promedio_emision": dias_promedio_emision,
        "total_canceladas": total_canceladas,
        "total_vigentes": total_vigentes,
        "ticket_promedio_prima": ticket_promedio_prima,
        "composicion_origen_emisiones": {
            "prospectos_nuevos": prospectos_nuevos,
            "cuentas_existentes": cuentas_existentes,
            "pct_origen_prospectos": (
                round(prospectos_nuevos / polizas_emitidas_total * 100, 2) if polizas_emitidas_total else 0.0
            ),
            "pct_origen_cuentas_existentes": (
                round(cuentas_existentes / polizas_emitidas_total * 100, 2) if polizas_emitidas_total else 0.0
            ),
        },
        "composicion_inmediatez_emisiones": {
            "mismo_periodo": emisiones_mismo_periodo,
            "arrastre_pasado": emisiones_arrastre_pasado,
            "pct_mismo_periodo": (
                round(emisiones_mismo_periodo / polizas_emitidas_total * 100, 2) if polizas_emitidas_total else 0.0
            ),
            "pct_arrastre_pasado": (
                round(emisiones_arrastre_pasado / polizas_emitidas_total * 100, 2) if polizas_emitidas_total else 0.0
            ),
        },
        "distribucion_ramo_emisiones": distribucion_ramo_emisiones,
    }


def _resolver_origen_item(item: Dict[str, Any]) -> str:
    """
    Origen_de_oportunidad__c si el item tiene oportunidad, LeadSource si
    no. 'Sin identificar' si el campo aplicable viene vacío. Duplicado a
    propósito de ranking_asesores.py (mismo criterio) para no crear una
    dependencia cruzada entre ambos módulos.
    """
    opp = item.get("oportunidad")
    if opp:
        origen = opp.get("origen_oportunidad")
    else:
        prospecto = item.get("prospecto") or {}
        origen = prospecto.get("lead_source")
    return origen or "Sin identificar"


def calcular_metricas_cohorte(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Métricas de cohorte y eficiencia sobre los items YA acotados por la
    consulta principal (Lead/Opportunity con CreatedDate en el rango
    solicitado, más los filtros status_lead/stage_opp/ramo/con_folio ya
    aplicados). No requiere una consulta adicional: solo clasifica el
    resultado de cada oportunidad ya traída, según si su folio se emitió
    (o no) dentro del mismo rango con el que se trajo esa oportunidad.

    Nota: si el filtro usado es 'periodo' (no fecha_inicio/fecha_fin), los
    items ya vienen acotados por filtrar_por_periodo, cuya regla de
    inclusión es "cualquier fecha del Lead/Oportunidad/Folio en el
    periodo" — por lo que 'oportunidades_generadas' aquí podría incluir
    alguna oportunidad cuyo propio CreatedDate no esté en el periodo pero
    sí lo esté, por ejemplo, la fecha de su folio. Con fecha_inicio/
    fecha_fin explícitos (el caso principal) esto no ocurre, porque ahí sí
    se acota directamente por CreatedDate en la consulta SOQL.
    """
    leads_registrados = 0
    convertidos = 0
    oportunidades_generadas = 0
    emisiones_mismo_periodo = 0
    emisiones_provenientes_de_lead = 0
    oportunidades_no_emitidas = 0
    oportunidades_en_proceso = 0
    monto_total_cotizado = 0.0
    origenes: Dict[str, Dict[str, int]] = {}

    for item in items:
        prospecto = item.get("prospecto")
        if prospecto is not None:
            leads_registrados += 1
            if prospecto.get("is_converted"):
                convertidos += 1

        opp = item.get("oportunidad")
        origen_registro = item.get("origen_registro")

        # distribucion_origen: un origen por item (oportunidad, o
        # prospecto sin oportunidad); 'emitidas' se completa abajo.
        origen_item = None
        if opp or (prospecto is not None and opp is None):
            origen_item = _resolver_origen_item(item)
            origenes.setdefault(origen_item, {"total": 0, "emitidas": 0})
            origenes[origen_item]["total"] += 1

        tiene_emitida = False
        if opp:
            oportunidades_generadas += 1
            monto_total_cotizado += opp.get("prima_total_cotizada") or 0.0

            # Doble señal: por folio (Case.Poliza_emitida__c/Poliza_no_emitida__c)
            # y por StageName de la propia oportunidad. Algunas oportunidades
            # "Póliza no emitida" nunca llegan a tener un Case asociado (se
            # descartan antes de generar folio), así que depender solo del
            # folio subcuenta esos casos como "en proceso" incorrectamente.
            stage = (opp.get("stage_name") or "").strip().lower()
            tiene_emitida = stage == "póliza emitida"
            tiene_no_emitida = stage == "póliza no emitida"

            for folio in item.get("folios_emision", []):
                if folio.get("poliza_emitida"):
                    tiene_emitida = True
                elif folio.get("poliza_no_emitida"):
                    tiene_no_emitida = True

            if tiene_emitida:
                emisiones_mismo_periodo += 1
                if origen_registro == "PROSPECTO_CONVERTIDO":
                    emisiones_provenientes_de_lead += 1
            elif tiene_no_emitida:
                oportunidades_no_emitidas += 1
            else:
                oportunidades_en_proceso += 1

        if origen_item is not None and tiene_emitida:
            origenes[origen_item]["emitidas"] += 1

    # EJE A: Prospección (Leads Nuevos) — sobre leads_registrados.
    tasa_conversion_prospecto_pct = round(convertidos / leads_registrados * 100, 2) if leads_registrados else 0.0
    tasa_cierre_prospeccion_pct = (
        round(emisiones_provenientes_de_lead / leads_registrados * 100, 2) if leads_registrados else 0.0
    )

    # EJE B: Eficiencia Comercial (Oportunidades Totales) — sobre oportunidades_generadas.
    # No se mide oportunidades/leads: la mayoría de las oportunidades no
    # nacen de un Lead, esa relación distorsiona la lectura comercial.
    tasa_cierre_oportunidad_pct = (
        round(emisiones_mismo_periodo / oportunidades_generadas * 100, 2) if oportunidades_generadas else 0.0
    )
    tasa_oportunidades_perdidas_pct = (
        round(oportunidades_no_emitidas / oportunidades_generadas * 100, 2) if oportunidades_generadas else 0.0
    )

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

    return {
        "distribucion_origen": distribucion_origen,
        "gestion_cohorte_creacion": {
            "leads_registrados": leads_registrados,
            "oportunidades_generadas": oportunidades_generadas,
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
        },
        "metrica_financiera_cohorte": {
            "monto_total_cotizado": round(monto_total_cotizado, 2),
        },
    }


# ─── Capa 5: Filtro por periodo ───────────────────────────────────

def _parsear_periodo(periodo: str) -> Optional[Tuple[datetime, datetime]]:
    """
    Parsea un periodo en formato 'YYYY-MM' o 'YYYY-MM:YYYY-MM'.

    Returns:
        Tuple (inicio, fin) como datetimes, o None si el formato es inválido.
    """
    try:
        if ":" in periodo:
            inicio_str, fin_str = periodo.split(":", 1)
            inicio = datetime.strptime(inicio_str.strip(), "%Y-%m").replace(tzinfo=timezone.utc)
            fin = datetime.strptime(fin_str.strip(), "%Y-%m").replace(tzinfo=timezone.utc)
            # Fin = último día del mes de fin
            if fin.month == 12:
                fin_fin = fin.replace(day=31, hour=23, minute=59, second=59)
            else:
                fin_fin = fin.replace(month=fin.month + 1, day=1) - timedelta(seconds=1)
        else:
            inicio = datetime.strptime(periodo.strip(), "%Y-%m").replace(tzinfo=timezone.utc)
            if inicio.month == 12:
                fin_fin = inicio.replace(day=31, hour=23, minute=59, second=59)
            else:
                fin_fin = inicio.replace(month=inicio.month + 1, day=1) - timedelta(seconds=1)
        return inicio, fin_fin
    except (ValueError, TypeError):
        return None


def filtrar_por_periodo(
    items: List[Dict[str, Any]],
    periodo: str,
) -> List[Dict[str, Any]]:
    """
    Filtra items por periodo. Un item se incluye si el Lead, la Oportunidad
    o alguna Póliza tiene una fecha de creación dentro del periodo.

    Args:
        items: Lista de items de seguimiento.
        periodo: Periodo en formato 'YYYY-MM' o 'YYYY-MM:YYYY-MM'.

    Returns:
        Lista filtrada de items.
    """
    rango = _parsear_periodo(periodo)
    if rango is None:
        return items

    inicio, fin = rango
    filtrados = []
    for item in items:
        prospecto = item.get("prospecto") or {}
        opp = item.get("oportunidad")
        folios = item.get("folios_emision", [])

        # Incluir si el Lead cae en el periodo
        if _fecha_en_periodo(prospecto.get("created_date"), inicio, fin):
            filtrados.append(item)
            continue

        # Incluir si la Oportunidad cae en el periodo
        if opp and _fecha_en_periodo(opp.get("created_date"), inicio, fin):
            filtrados.append(item)
            continue

        # Incluir si algún Folio (Case) cae en el periodo
        if any(_fecha_en_periodo(folio.get("created_date"), inicio, fin) for folio in folios):
            filtrados.append(item)
            continue

    return filtrados


def filtrar_por_ramo(
    items: List[Dict[str, Any]],
    ramo: str,
) -> List[Dict[str, Any]]:
    """
    Filtra items por ramo. Un item se incluye si el prospecto, la
    oportunidad (Ramos_de_interes__c) o algún folio (Ramo__c) coincide
    con el ramo solicitado.

    Args:
        items: Lista de items de seguimiento.
        ramo: Uno de RAMOS_VALIDOS.

    Returns:
        Lista filtrada de items.
    """
    filtrados = []
    for item in items:
        prospecto = item.get("prospecto") or {}
        opp = item.get("oportunidad")
        folios = item.get("folios_emision", [])

        if prospecto.get("ramos_interes") == ramo:
            filtrados.append(item)
            continue

        if opp and opp.get("ramos_interes") == ramo:
            filtrados.append(item)
            continue

        if any(folio.get("ramo") == ramo for folio in folios):
            filtrados.append(item)
            continue

    return filtrados


# ─── Capa 6: Paginación en memoria ────────────────────────────────

def paginar_items(
    items: List[Dict[str, Any]],
    page: int,
    size: int,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Aplica paginación en memoria sobre una lista de items.

    Args:
        items: Lista completa de items.
        page: Índice de página (zero-based).
        size: Cantidad de registros por página.

    Returns:
        Tuple (items de la página, total de registros).
    """
    total_records = len(items)
    start = page * size
    end = start + size
    return items[start:end], total_records


# ─── Orquestador principal ────────────────────────────────────────

def obtener_trazabilidad_asesor(
    sf: Salesforce,
    numero_asesor: str,
    status_lead: Optional[str] = None,
    stage_opp: Optional[str] = None,
    ramo: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    periodo: Optional[str] = None,
    con_folio: Optional[bool] = None,
    page: int = 0,
    size: int = 10,
) -> Dict[str, Any]:
    """
    Orquesta la consulta de trazabilidad end-to-end de un asesor.

    Flujo:
    1. Resuelve el User activo (Alias = numero_asesor) y el nombre del asesor.
    2. Consulta todos los Leads del asesor por OwnerId (propietario principal).
    3. Extrae Oportunidades relacionadas en lote.
    4. Extrae Folios (Case) vinculados a las oportunidades en lote.
    5. Extrae Cuentas convertidas en lote.
    6. Ensambla items de seguimiento.
    7. Filtra por periodo (Lead, Oportunidad o Folio) si aplica.
    8. Filtra por ramo (Lead, Oportunidad o Folio) si aplica.
    9. Filtra por stage_opp (solo oportunidades) si aplica.
    10. Filtra por con_folio (solo items con folios de emisión) si aplica.
    11. Calcula KPIs sobre el total filtrado.
    11.5. Calcula producción del periodo (con arrastre, consulta aparte) y
          métricas de cohorte/eficiencia (aditivo, no reemplaza el paso 11).
    12. Calcula la fecha mínima de registro.
    13. Pagina en memoria.

    Returns:
        Dict con la estructura de respuesta (meta + items).
    """
    # ── 1. Resolver User y nombre del asesor ─────────────────────
    user_id = obtener_user_id_por_alias(sf, numero_asesor)
    nombre_asesor = obtener_nombre_asesor(sf, numero_asesor)

    # ── 2. Consultar todos los Leads del asesor (por OwnerId) ────
    leads = []
    if user_id:
        leads = consultar_leads_por_asesor(
            sf,
            user_id,
            status_lead=status_lead,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        )

    # ── 3. Consultar Oportunidades del asesor ────────────────────
    # Si se filtra por status_lead, solo se consultan las oportunidades
    # relacionadas a los leads filtrados (no todas las del asesor).
    # Si no hay filtro de status_lead, se consultan TODAS las oportunidades
    # del asesor (incluye venta directa en cuentas existentes).
    if status_lead:
        opp_ids = [
            lead["ConvertedOpportunityId"]
            for lead in leads
            if lead.get("ConvertedOpportunityId")
        ]
        oportunidades = consultar_oportunidades_en_lote(
            sf, opp_ids, stage_opp=stage_opp,
            fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        )
    else:
        oportunidades = {}
        if user_id:
            oportunidades = consultar_oportunidades_por_asesor(
                sf, user_id, stage_opp=stage_opp,
                fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
            )

    # ── 4. Extraer Folios (Case) en lote ─────────────────────────
    opp_ids = list(oportunidades.keys())
    folios_por_opp = consultar_folios_en_lote(sf, opp_ids)

    # ── 5. Extraer Cuentas convertidas en lote ───────────────────
    account_ids = [
        lead["ConvertedAccountId"]
        for lead in leads
        if lead.get("ConvertedAccountId")
    ]
    cuentas = consultar_cuentas_en_lote(sf, account_ids)

    # ── 6. Ensamblar items con clasificación de 3 escenarios ─────
    items = construir_items_unificada(leads, oportunidades, folios_por_opp, cuentas)

    # ── 7. Filtro por periodo (si aplica) ────────────────────────
    if periodo:
        items = filtrar_por_periodo(items, periodo)

    # ── 8. Filtro por ramo (Lead, Oportunidad o Folio) si aplica ──
    if ramo:
        items = filtrar_por_ramo(items, ramo)

    # ── 9. Filtro por stage_opp (solo oportunidades) ─────────────
    # El filtro stage_opp ya se aplicó en la query de oportunidades.
    # Solo se conservan los items que tienen una oportunidad en esa etapa;
    # los leads sin oportunidad (no convertidos o en otra etapa) se excluyen.
    # "Otros" captura etapas inactivas/rezagadas que no están en el catálogo.
    if stage_opp:
        if stage_opp == "Otros":
            items = [
                item for item in items
                if item.get("oportunidad") is not None
                and (item["oportunidad"].get("stage_name") or "").strip().lower()
                not in {s.lower() for s in STAGE_OPP_VALIDOS if s != "Otros"}
            ]
        else:
            items = [item for item in items if item.get("oportunidad") is not None]

    # ── 10. Filtro por con_folio (solo items con folios de emisión) ─
    if con_folio is not None:
        if con_folio:
            items = [item for item in items if item.get("folios_emision")]
        else:
            items = [item for item in items if not item.get("folios_emision")]

    # ── 11. Calcular KPIs sobre el total filtrado ────────────────
    kpis = calcular_kpis(items)

    # ── 11.5. Producción del periodo vs. cohorte (aditivo) ────────
    # No reemplaza nada de kpis; agrega la distinción producción/cohorte.
    metricas_cohorte = calcular_metricas_cohorte(items)

    # Mezcla de venta / origen de oportunidades (EJE B): usa el desglose
    # cuentas_existentes/prospectos que ya calcula calcular_kpis sobre los
    # mismos items, expresado como % de oportunidades_generadas.
    origen_oportunidades = kpis["detalle_oportunidades"]["origen"]
    oportunidades_generadas_cohorte = metricas_cohorte["gestion_cohorte_creacion"]["oportunidades_generadas"]
    metricas_cohorte["eficiencia_comercial"]["pct_origen_cuentas_existentes"] = (
        round(origen_oportunidades["cuentas_existentes"] / oportunidades_generadas_cohorte * 100, 2)
        if oportunidades_generadas_cohorte else 0.0
    )
    metricas_cohorte["eficiencia_comercial"]["pct_origen_prospectos"] = (
        round(origen_oportunidades["prospectos"] / oportunidades_generadas_cohorte * 100, 2)
        if oportunidades_generadas_cohorte else 0.0
    )

    produccion_periodo_cierre = None
    if user_id:
        try:
            produccion_periodo_cierre = calcular_produccion_periodo(
                sf, user_id, fecha_inicio, fecha_fin, periodo
            )
        except Exception as e:
            print(f"Error al calcular producción del periodo para {numero_asesor}: {e}")

    # ── 12. Calcular fecha mínima de registro ────────────────────
    # Considera la fecha de creación más antigua entre prospectos,
    # oportunidades y folios.
    fecha_minima = None
    fechas = []
    for item in items:
        prospecto = item.get("prospecto") or {}
        created = prospecto.get("created_date")
        if created:
            fechas.append(created)

        opp = item.get("oportunidad")
        if opp and opp.get("created_date"):
            fechas.append(opp["created_date"])

        for folio in item.get("folios_emision", []):
            if folio.get("created_date"):
                fechas.append(folio["created_date"])

    if fechas:
        fecha_minima = min(fechas)

    # ── 13. Paginar en memoria ───────────────────────────────────
    items_pagina, total_records = paginar_items(items, page, size)
    total_pages = (total_records + size - 1) // size if size > 0 else 0

    return {
        "status": "success",
        "meta": {
            "numero_asesor": numero_asesor,
            "nombre_asesor": nombre_asesor,
            "fecha_minima": fecha_minima,
            "resumen_ejecutivo": kpis["resumen_ejecutivo"],
            "detalle_prospeccion": kpis["detalle_prospeccion"],
            "detalle_oportunidades": kpis["detalle_oportunidades"],
            "detalle_folios_tramite": kpis["detalle_folios_tramite"],
            "detalle_ramos": kpis["detalle_ramos"],
            "produccion_periodo_cierre": produccion_periodo_cierre,
            "gestion_cohorte_creacion": metricas_cohorte["gestion_cohorte_creacion"],
            "eficiencia_prospeccion": metricas_cohorte["eficiencia_prospeccion"],
            "eficiencia_comercial": metricas_cohorte["eficiencia_comercial"],
            "metrica_financiera_cohorte": metricas_cohorte["metrica_financiera_cohorte"],
            "distribucion_origen": metricas_cohorte["distribucion_origen"],
            "pagination": {
                "page": page,
                "size": size,
                "total_pages": total_pages,
                "total_records": total_records,
            },
            "filtros_aplicados": {
                "status_lead": status_lead,
                "stage_opp": stage_opp,
                "ramo": ramo,
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "periodo": periodo,
                "con_folio": con_folio,
            },
        },
        "items": items_pagina,
    }
