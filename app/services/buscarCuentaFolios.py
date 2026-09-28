from typing import Optional

import dateutil.parser
from simple_salesforce import Salesforce

from app.dependencias.sf_service import query_con_reintento
from app.services.buscarFolio import ajustar_horas
from app.services.contacto_cuenta import _buscar_cuenta_por_expediente_exacto
from app.utils.diccionarios import normalizacion_expediente, tipo_folios

RECORD_TYPE_CONTACTO = "Contacto"


# ─── Normalización del expediente según empresa ───────────────────

def _normalizar_numerico(expediente: str, tamano: int) -> str:
    """Completa con ceros a la izquierda si es más corto, o quita ceros
    sobrantes a la izquierda si es más largo de lo esperado."""
    limpio = expediente
    if len(limpio) > tamano:
        limpio = limpio.lstrip("0") or "0"
    return limpio.zfill(tamano)


def _normalizar_rfc(expediente: str, tamano: int) -> str:
    """Completa con ceros a la izquierda si es más corto, o trunca los
    caracteres sobrantes al final (descarta la homoclave) si es más largo."""
    limpio = expediente
    if len(limpio) > tamano:
        return limpio[:tamano]
    return limpio.zfill(tamano)


def normalizar_expediente(expediente: str, empresa: str) -> str:
    """
    Normaliza el expediente al tamaño esperado según la empresa, usando el
    catálogo normalizacion_expediente.REGLAS. Si la empresa no está en el
    catálogo, retorna el expediente tal cual fue recibido.
    """
    regla = normalizacion_expediente.REGLAS.get(empresa.strip().upper())
    if regla is None:
        return expediente

    if regla["tipo"] == "rfc":
        return _normalizar_rfc(expediente, regla["tamano"])
    return _normalizar_numerico(expediente, regla["tamano"])


# ─── Búsqueda de cuenta ────────────────────────────────────────────

def buscar_cuenta_por_expediente_empresa(sf: Salesforce, expediente: str, empresa: str) -> Optional[dict]:
    """
    Busca la cuenta asociada a un expediente, normalizándolo primero según
    el tamaño esperado para la empresa recibida.

    Como última alternativa, si no se encuentra con el expediente
    normalizado, se busca con el expediente tal cual fue recibido.
    """
    expediente_original = expediente.strip()
    expediente_normalizado = normalizar_expediente(expediente_original, empresa)

    print(f"Buscando cuenta con expediente normalizado: {expediente_normalizado}")
    account = _buscar_cuenta_por_expediente_exacto(sf, expediente_normalizado)
    if account is not None:
        return account

    if expediente_normalizado != expediente_original:
        print(f"Buscando cuenta con expediente tal cual fue recibido: {expediente_original}")
        account = _buscar_cuenta_por_expediente_exacto(sf, expediente_original)
        if account is not None:
            return account

    return None


# ─── Motivo de folio (tipo de movimiento de los folios de Contacto) ───

def _obtener_etiquetas_por_case(sf: Salesforce, case_ids: list) -> dict:
    """
    Para folios de Contacto, Tipo_de_movimiento__c no existe en el Case:
    el equivalente se registra en Motivo_de_folio__c.Etiqueta__c, asociado
    al Case por Folio__c. Retorna un dict {case_id: nombre_etiqueta}.
    """
    if not case_ids:
        return {}

    ids_formateados = ", ".join(f"'{case_id}'" for case_id in case_ids)
    query = (
        "SELECT Folio__c, Etiqueta__r.Name "
        "FROM Motivo_de_folio__c "
        f"WHERE Folio__c IN ({ids_formateados})"
    )
    result = query_con_reintento(sf, query)

    etiquetas_por_case = {}
    for r in result["records"]:
        etiqueta = r.get("Etiqueta__r") or {}
        etiquetas_por_case[r.get("Folio__c")] = etiqueta.get("Name")

    return etiquetas_por_case


# ─── Folios de la cuenta ───────────────────────────────────────────

def obtener_folios_de_cuenta(sf: Salesforce, account_id: str) -> list:
    """
    Recupera el listado resumido de folios (Case) asociados a una cuenta, en
    una sola consulta (igual que el servicio de referencia /cuentas/folios):
    CaseNumber, Estado, Tipo_movimiento, Poliza_asociada, Tipo, Fecha_creacion.

    El Estado se traduce con el mismo catálogo que usa buscar_folio()
    (tipo_folios.recordType_map), sin llamar a buscar_folio() por cada Case
    (eso implicaba una consulta extra a Salesforce por folio).

    Única variación para los folios de Contacto: Tipo_movimiento no existe en
    el Case, se resuelve aparte desde Motivo_de_folio__c.Etiqueta__c (una
    sola consulta adicional, no por folio).
    """
    query = (
        "SELECT Id, CaseNumber, Status, Tipo_de_movimiento__c, "
        "P_liza_de_seguro__r.Name, CreatedDate, RecordType.Name "
        "FROM Case "
        f"WHERE AccountId = '{account_id}' "
        "AND RecordType.Name NOT IN ('7.- Posible cancelación') "
        "ORDER BY CreatedDate DESC"
    )
    result = query_con_reintento(sf, query)
    records = result["records"]

    # ── Resolver tipo de movimiento de los folios de Contacto ────────
    case_ids_contacto = []
    for r in records:
        record_type = r.get("RecordType") or {}
        tipo_folio = record_type.get("Name")
        tipo_folio = tipo_folio[4:] if tipo_folio else None
        if tipo_folio == RECORD_TYPE_CONTACTO:
            case_ids_contacto.append(r.get("Id"))

    etiquetas_por_case = _obtener_etiquetas_por_case(sf, case_ids_contacto)

    folios = []
    for r in records:
        record_type = r.get("RecordType") or {}
        tipo_folio = record_type.get("Name")
        if tipo_folio:
            tipo_folio = tipo_folio[4:]

        if tipo_folio == RECORD_TYPE_CONTACTO:
            tipo_movimiento = etiquetas_por_case.get(r.get("Id"))
        else:
            tipo_movimiento = r.get("Tipo_de_movimiento__c")

        status_dict_name = tipo_folios.recordType_map.get(tipo_folio)
        status_dict = getattr(tipo_folios, status_dict_name, {}) if status_dict_name else {}
        estado = status_dict.get(r.get("Status"), r.get("Status"))

        poliza = r.get("P_liza_de_seguro__r") or {}

        fecha_creacion = r.get("CreatedDate")
        if fecha_creacion:
            fecha_creacion = dateutil.parser.parse(ajustar_horas(fecha_creacion))

        folios.append({
            "CaseNumber": r.get("CaseNumber"),
            "Estado": estado,
            "Tipo_movimiento": tipo_movimiento,
            #"Poliza_asociada": poliza.get("Name"),
            "Tipo": tipo_folio,
            "Fecha_creacion": fecha_creacion,
        })

    return folios
