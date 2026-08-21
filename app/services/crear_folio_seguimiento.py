from typing import Optional, Tuple

from fastapi import HTTPException
from simple_salesforce import Salesforce

from app.dependencias.sf_service import (
    SesionExpiradaError,
    es_error_sesion,
    get_salesforce_data,
    query_con_reintento,
)
from app.models.schemas import CrearFolioRequest
from app.services.contacto_cuenta import buscar_cuenta_contacto
from app.services.crearCortizacion import buscar_asesor_activo
from app.services.sf_create_data import crear_nota_generica, crear_tarea_folio, obtener_record_type_id


# ─── Constantes ───────────────────────────────────────────────────

RECORD_TYPE_CASE = "3.- Mantenimiento"
RECORD_TYPE_CONTACTO = "9.- Contacto"
OFICINA = "MCB Cervantes"
ORIGEN_DEFAULT = "Lucia"
COLA_EJECUTIVOS_SAC = "Ejecutivos SAC"
OWNER_RESPALDO_SAC = "005WR000000OCC9YAO"
MENSAJE_RESPALDO_ASESOR = "Pronto se le asignará un asesor"


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
    2. GMM: coincide por Numero_de_endoso__c exacto, o por el segmento tras
       el guion en Name (ej. Name "42682042-12381" para certificado "0012381D")
       Otros ramos: coincide por Name (exacto, luego quitando ceros)
    3. Si hay varias coincidencias, toma la de EffectiveDate más reciente

    Args:
        account_id: ID de la cuenta (NameInsuredId).
        numero_poliza: Número de póliza/certificado del request.
        ramo: Ramo (si es "GMM", filtra por Producto__c = 'LINEA AZUL' y usa
            el emparejamiento por Numero_de_endoso__c / segmento de Name).
        sf: Instancia autenticada de Salesforce.

    Returns:
        Dict con la póliza encontrada (Id, Name, EffectiveDate), o None.
    """
    es_gmm = bool(ramo and ramo.strip().upper() == "GMM")

    # ── 1. Consultar pólizas de la cuenta ────────────────────────
    campos = "Id, Name, EffectiveDate"
    if es_gmm:
        campos += ", Numero_de_endoso__c"

    query = (
        f"SELECT {campos} "
        "FROM InsurancePolicy "
        f"WHERE NameInsuredId = '{account_id}'"
    )
    if es_gmm:
        query += " AND Producto__c = 'LINEA AZUL'"
        print("Ramo GMM → filtrando por Producto__c = 'LINEA AZUL'")

    result = query_con_reintento(sf, query)

    if result['totalSize'] == 0:
        print("No se encontraron pólizas asociadas a esta cuenta")
        return None

    # ── 2. Coincidir por Name / Numero_de_endoso__c ───────────────
    poliza_limpia = numero_poliza.strip()
    poliza_formateada = formatear_certificado(poliza_limpia)

    coincidencias = []
    for record in result['records']:
        record_name = record.get('Name', '') or ''

        if es_gmm:
            # Coincidencia por número de endoso exacto
            if record.get('Numero_de_endoso__c') == poliza_limpia:
                coincidencias.append(record)
                continue

            # Coincidencia por el segmento tras el guion en Name
            if '-' in record_name:
                certificado = record_name.split('-')[-1].strip()
                if certificado == poliza_formateada:
                    coincidencias.append(record)
                    continue

            continue

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


def asignar_propietario_carrusel_folio(
    sf: Salesforce,
    origen_folio: str,
    nombre_record_type: str,
    nombre_cola: str = COLA_EJECUTIVOS_SAC
) -> Tuple[str, str]:
    """
    Asigna un folio (Case) a un asesor de la cola de folios por carrusel.

    Misma lógica que asignar_propietario_carrusel (cotización), pero:
    - La disponibilidad se revisa en la cola `nombre_cola` (Ejecutivos SAC).
    - La rotación se basa en los últimos 5 Case (no Lead) creados por nuestro
      usuario de integración, filtrados por Origin y RecordType, para que
      folios de Mantenimiento y de Contacto roten de forma independiente.

    Returns:
        Tuple (owner_id, nombre_asesor)
    """
    try:
        owners_list = buscar_asesor_activo(sf, nombre_cola=nombre_cola)
        size = len(owners_list)

        if size == 0:
            print(f"Omni-Channel vacío en '{nombre_cola}'. Asignando a respaldo.")
            return OWNER_RESPALDO_SAC, MENSAJE_RESPALDO_ASESOR

        owners_list.sort(key=lambda x: x['id'])
        print(f"DEBUG: Asesores disponibles y ordenados para el carrusel de folios: {owners_list}")

        just_ids = [owner['id'] for owner in owners_list]

        query_ultimos = (
            "SELECT OwnerId FROM Case WHERE CreatedBy.Name = 'Integraciones Desarrollo Digital' "
            f"AND Origin = '{origen_folio}' AND RecordType.Name = '{nombre_record_type}' "
            "ORDER BY CreatedDate DESC LIMIT 5"
        )

        last_owners_ids = []
        try:
            res_ultimos = query_con_reintento(sf, query_ultimos)
            for record in res_ultimos['records']:
                last_owners_ids.append(record['OwnerId'])
            print(f"DEBUG: Últimos Owners de folios '{nombre_record_type}'/'{origen_folio}': {last_owners_ids}")
        except Exception as e:
            print(f"Error al consultar últimos folios de '{origen_folio}': {e}")

        start_index = 0
        for last_owner in last_owners_ids:
            if last_owner in just_ids:
                start_index = (just_ids.index(last_owner) + 1) % size
                print(f"DEBUG: El último en atender fue {last_owner}. Turno inicial para índice: {start_index}")
                break

        candidato = owners_list[start_index]

        print(f"¡Folio asignado por carrusel! -> ID: {candidato['id']}, Nombre: {candidato['name']}")
        return candidato['id'], candidato['name']

    except Exception as e:
        print(f"Error en la asignación de folio: {e}")
        return OWNER_RESPALDO_SAC, MENSAJE_RESPALDO_ASESOR


# ─── Orquestador principal ────────────────────────────────────────

def crear_folio_seguimiento(
    request: CrearFolioRequest,
    sf: Salesforce
) -> Tuple[str, Optional[str], Optional[str], str]:
    """
    Crea un folio de seguimiento (Case) en Salesforce.

    Flujo:
    1. Busca la cuenta por expediente (búsqueda en cascada)
    2. Si viene numero_poliza, busca la póliza asociada a la cuenta.
       - Si se encuentra → folio de Mantenimiento ('3.- Mantenimiento').
       - Si no viene numero_poliza, o no se encuentra la póliza →
         folio de contingencia de Contacto ('9.- Contacto'), asociado
         únicamente a la cuenta.
    3. Resuelve el asesor asignado (carrusel sobre la cola 'Ejecutivos SAC')
    4. Crea el Case con los datos del folio
    5. Crea la tarea de seguimiento para el asesor asignado
    6. Crea nota de contacto (correo/teléfono) en el Case

    Returns:
        Tuple (case_id, case_number, case_link, nombre_asesor)
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

    origen = request.origen_folio.strip() if request.origen_folio and request.origen_folio.strip() else ORIGEN_DEFAULT

    # ── 2. Buscar póliza (si se proporcionó) y armar datos del Case ──
    numero_poliza = request.numero_poliza.strip() if request.numero_poliza else ""
    poliza = _buscar_poliza_cuenta(account_id, numero_poliza, request.ramo, sf) if numero_poliza else None

    if poliza is not None:
        nombre_record_type = RECORD_TYPE_CASE
        record_type_id = obtener_record_type_id(sf, 'Case', nombre_record_type)
        case_data = {
            'RecordTypeId': record_type_id,
            'AccountId': account_id,
            'P_liza_de_seguro__c': poliza['Id'],
            'Tipo_de_movimiento__c': request.tipo_movimiento,
            'Origin': origen,
            'Oficina__c': OFICINA,
        }
    else:
        print(
            "No se proporcionó número de póliza o no se encontró; "
            f"creando folio de contingencia '{RECORD_TYPE_CONTACTO}'."
        )
        nombre_record_type = RECORD_TYPE_CONTACTO
        record_type_id = obtener_record_type_id(sf, 'Case', nombre_record_type)
        case_data = {
            'RecordTypeId': record_type_id,
            'AccountId': account_id,
        }

    # ── 3. Resolver asesor asignado por carrusel ('Ejecutivos SAC') ──
    owner_id, nombre_asesor = asignar_propietario_carrusel_folio(sf, origen, nombre_record_type)
    case_data['OwnerId'] = owner_id
    print(f"Asesor asignado al folio: {nombre_asesor}")

    # ── 4. Crear el Case ─────────────────────────────────────────
    # Re-obtener sesión de Salesforce tras la cadena de lecturas previas,
    # para que la escritura use una sesión válida.
    print("Re-obteniendo sesión de Salesforce antes de crear el Case...")
    sf = get_salesforce_data()

    try:
        new_case = sf.Case.create(case_data)
        case_id = new_case.get('id')
        print(f"Case creado con ID: {case_id}")
    except Exception as e:
        error_str = str(e)
        print(f"Error al crear el Case: {e}")
        if es_error_sesion(e):
            print("Sesión expirada al crear el Case.")
            raise SesionExpiradaError(error_str) from e
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

    # ── 5. Crear tarea de seguimiento para el asesor asignado ────
    descripcion_tarea = f"Folio de seguimiento ({nombre_record_type}) - Cuenta: {account.get('Name', '')}"
    crear_tarea_folio(sf, case_id, owner_id, descripcion_tarea)

    # ── 6. Crear nota de contacto ────────────────────────────────
    _crear_nota_contacto(case_id, request, sf)

    print(f"Folio de seguimiento creado: {case_id} - {case_number}")
    return case_id, case_number, case_link, nombre_asesor