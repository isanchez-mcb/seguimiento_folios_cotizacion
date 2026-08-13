from typing import Optional, Tuple

from fastapi import HTTPException
from simple_salesforce import Salesforce

from app.dependencias.sf_service import query_con_reintento
from app.models.schemas import CrearFolioRequest
from app.services.contacto_cuenta import buscar_cuenta_contacto
from app.services.sf_create_data import crear_nota_generica, obtener_record_type_id


# ─── Constantes ───────────────────────────────────────────────────

RECORD_TYPE_CASE = "3.- Mantenimiento"
TIPO_MOVIMIENTO = "Duplicado"
OFICINA = "MCB Cervantes"
ORIGEN_DEFAULT = "Lucia"


# ─── Helpers ──────────────────────────────────────────────────────

def formatear_certificado(certificado: str) -> str:
    """
    Formatea un número de póliza/certificado:
    - Quita espacios
    - Si termina en letra, la quita
    - Quita ceros a la izquierda
    
    Ejemplo: "000123A" → "123"
    """
    endoso = certificado.strip()
    if endoso and endoso[-1].isalpha():
        endoso = endoso[:-1]

    endoso = endoso.lstrip("0")
    print(f"Certificado formateado: {endoso}")
    return endoso


def _buscar_poliza_cuenta(
    account_id: str,
    numero_poliza: str,
    ramo: Optional[str],
    sf: Salesforce
) -> Optional[dict]:
    """
    Busca una póliza (InsurancePolicy) asociada a la cuenta.
    
    Estrategia:
    1. Consulta todas las pólizas de la cuenta (con filtro GMM si aplica)
    2. Coincide por Name (exacto, luego quitando ceros)
    3. Si hay varias coincidencias, toma la de EffectiveDate más reciente
    
    Args:
        account_id: ID de la cuenta (NameInsuredId).
        numero_poliza: Número de póliza del request.
        ramo: Ramo (si es "GMM", filtra por Producto__c = 'LINEA AZUL').
        sf: Instancia autenticada de Salesforce.
    
    Returns:
        Dict con la póliza encontrada (Id, Name, EffectiveDate), o None.
    """
    # ── 1. Consultar pólizas de la cuenta ────────────────────────
    query = (
        "SELECT Id, Name, EffectiveDate "
        "FROM InsurancePolicy "
        f"WHERE NameInsuredId = '{account_id}'"
    )
    if ramo and ramo.strip().upper() == "GMM":
        query += " AND Producto__c = 'LINEA AZUL'"
        print("Ramo GMM → filtrando por Producto__c = 'LINEA AZUL'")

    result = query_con_reintento(sf, query)

    if result['totalSize'] == 0:
        print("No se encontraron pólizas asociadas a esta cuenta")
        return None

    # ── 2. Coincidir por Name ────────────────────────────────────
    poliza_limpia = numero_poliza.strip()
    poliza_formateada = formatear_certificado(poliza_limpia)

    coincidencias = []
    for record in result['records']:
        record_name = record.get('Name', '') or ''
        record_name_formateado = formatear_certificado(record_name)

        # Coincidencia exacta
        if record_name == poliza_limpia:
            coincidencias.append(record)
            continue

        # Coincidencia quitando ceros
        if record_name_formateado == poliza_formateada:
            coincidencias.append(record)
            continue

    if not coincidencias:
        print(f"No se encontró póliza con número: {numero_poliza}")
        return None

    # ── 3. Si hay varias, tomar la de EffectiveDate más reciente ─
    if len(coincidencias) > 1:
        print(f"Se encontraron {len(coincidencias)} pólizas. Tomando la de vigencia más actual...")
        coincidencias.sort(key=lambda r: r.get('EffectiveDate') or '', reverse=True)

    poliza = coincidencias[0]
    print(f"Póliza encontrada: {poliza.get('Id')} - {poliza.get('Name')} (EffectiveDate: {poliza.get('EffectiveDate')})")
    return poliza


def _crear_nota_contacto(case_id: str, request: CrearFolioRequest, sf: Salesforce) -> bool:
    """
    Crea una ContentNote en el Case con los datos de contacto (correo/teléfono).
    
    Args:
        case_id: ID del Case al que asociar la nota.
        request: Datos del formulario.
        sf: Instancia autenticada de Salesforce.
    
    Returns:
        True si se creó correctamente, False en caso contrario.
    """
    origen = request.origen_folio.strip() if request.origen_folio and request.origen_folio.strip() else ORIGEN_DEFAULT

    # Construir contenido HTML con los datos de contacto disponibles
    partes = ["<ul>"]
    if request.correo and request.correo.strip():
        partes.append(f"<li><b>Correo:</b> {request.correo.strip()}</li>")
    if request.telefono and request.telefono.strip():
        partes.append(f"<li><b>Teléfono:</b> {request.telefono.strip()}</li>")
    partes.append("</ul>")

    html_content = "".join(partes)
    titulo_nota = f"Contacto - {origen}"

    nota_creada = crear_nota_generica(case_id, sf, html_content, titulo_nota)
    if nota_creada:
        print(f"Nota de contacto creada para case {case_id}")
    else:
        print(f"ERROR: No se pudo crear la nota de contacto para case {case_id}")
    return nota_creada


# ─── Orquestador principal ────────────────────────────────────────

def crear_folio_seguimiento(
    request: CrearFolioRequest,
    sf: Salesforce
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Crea un folio de seguimiento (Case) en Salesforce.
    
    Flujo:
    1. Busca la cuenta por expediente (búsqueda en cascada)
    2. Obtiene RecordTypeId de '3.- Mantenimiento' por nombre
    3. Busca la póliza asociada a la cuenta
    4. Crea el Case con los datos del folio
    5. Crea nota de contacto (correo/teléfono) en el Case
    
    Returns:
        Tuple (case_id, case_number, case_link)
    """
    # ── 1. Buscar cuenta por expediente ──────────────────────────
    account = buscar_cuenta_contacto(sf, request.expediente_colaborador)
    if account is None or not account.get('Id'):
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró cuenta con el expediente: {request.expediente_colaborador}"
        )

    account_id = account['Id']
    print(f"Cuenta encontrada: {account_id} - {account.get('Name', '')}")

    # ── 2. Obtener RecordTypeId por nombre ───────────────────────
    record_type_id = obtener_record_type_id(sf, 'Case', RECORD_TYPE_CASE)
    print(f"RecordTypeId de '{RECORD_TYPE_CASE}': {record_type_id}")

    # ── 3. Buscar póliza asociada a la cuenta ────────────────────
    poliza = _buscar_poliza_cuenta(account_id, request.numero_poliza, request.ramo, sf)
    if poliza is None:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró póliza con número: {request.numero_poliza} para la cuenta {account.get('Name', '')}"
        )

    poliza_id = poliza['Id']

    # ── 4. Crear el Case ─────────────────────────────────────────
    origen = request.origen_folio.strip() if request.origen_folio and request.origen_folio.strip() else ORIGEN_DEFAULT

    case_data = {
        'RecordTypeId': record_type_id,
        'AccountId': account_id,
        'P_liza_de_seguro__c': poliza_id,
        'Tipo_de_movimiento__c': TIPO_MOVIMIENTO,
        'LeadSource': origen,
        'Oficina__c': OFICINA,
    }

    try:
        new_case = sf.Case.create(case_data)
        case_id = new_case.get('id')
        print(f"Case creado con ID: {case_id}")
    except Exception as e:
        print(f"Error al crear el Case: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error al crear el folio de seguimiento: {str(e)}"
        )

    # Obtener CaseNumber y construir link
    case_number = None
    case_link = None
    try:
        case_record = sf.Case.get(case_id)
        case_number = case_record.get('CaseNumber')
        case_link = (
            f"https://customer-customer-9846.lightning.force.com/lightning/r/Case/{case_id}/view"
        )
        print(f"CaseNumber: {case_number}")
    except Exception as e:
        print(f"Error al obtener CaseNumber: {e}")

    # ── 5. Crear nota de contacto ────────────────────────────────
    _crear_nota_contacto(case_id, request, sf)

    print(f"Folio de seguimiento creado: {case_id} - {case_number}")
    return case_id, case_number, case_link