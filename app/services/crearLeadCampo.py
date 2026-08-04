from typing import List, Optional, Tuple

from fastapi import HTTPException
from simple_salesforce import Salesforce

from app.models.schemas import CreateLeadCampoRequest
from app.services.buscarAsesorExterno import buscar_asesor_externo, verificar_cuenta_usuario
from app.services.sf_create_data import createLead, crear_nota_generica
from app.utils.diccionarios import negocios_lead_campo


# ─── Constantes ───────────────────────────────────────────────────

RECORD_TYPE_MASIVO = "Masivo"
RECORD_TYPE_NN = "Persona física - Nuevos negocios"


# ─── Helpers ──────────────────────────────────────────────────────

def _resolver_empresa(codigo_empresa: Optional[str]) -> Optional[str]:
    """
    Traduce el código corto del frontend al nombre completo de Salesforce
    usando el catálogo negocios_lead_campo de diccionarios.py.
    
    - "STRM" → "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA"
    - "BIMBO" → "GRUPO BIMBO, S.A.B. DE C.V."
    - "" o "NN" o None → None (Nuevos Negocios, sin Negocio__c)
    
    Para agregar un nuevo negocio, solo hay que añadirlo en
    negocios_lead_campo.MAPEO en app/utils/diccionarios.py.
    """
    if not codigo_empresa:
        return None

    codigo = codigo_empresa.strip().upper()

    if codigo in ("NN", ""):
        return None

    entrada = negocios_lead_campo.MAPEO.get(codigo)
    if entrada:
        return entrada["nombre_sf"]

    # Si no está en el catálogo, pasar el valor tal cual
    return codigo_empresa.strip()


def _obtener_record_type_id(sf: Salesforce, nombre_empresa: Optional[str]) -> str:
    """
    Determina el RecordTypeId del Lead según la empresa resuelta.
    
    - Si empresa está en el catálogo negocios_lead_campo → "Masivo"
    - Si empresa es None (NN/vacío) → "Persona física - Nuevos negocios"
    """
    nombres_sf = {v["nombre_sf"].upper() for v in negocios_lead_campo.MAPEO.values()}

    if nombre_empresa and nombre_empresa.strip().upper() in nombres_sf:
        nombre_record_type = RECORD_TYPE_MASIVO
    else:
        nombre_record_type = RECORD_TYPE_NN

    query = (
        "SELECT Id FROM RecordType "
        f"WHERE SObjectType = 'Lead' AND Name = '{nombre_record_type}'"
    )
    result = sf.query(query)

    if result['totalSize'] == 0:
        raise HTTPException(
            status_code=500,
            detail=f"No se encontró RecordType '{nombre_record_type}' para Lead"
        )

    return result['records'][0]['Id']


def _requiere_expediente(nombre_empresa: Optional[str]) -> bool:
    """
    Verifica si un negocio requiere expediente según el catálogo.
    Retorna True por defecto si el negocio no está en el catálogo.
    """
    if not nombre_empresa:
        return False

    nombre_upper = nombre_empresa.strip().upper()
    for v in negocios_lead_campo.MAPEO.values():
        if v["nombre_sf"].upper() == nombre_upper:
            return v["requiere_expediente"]

    return True  # Por defecto, asumir que requiere expediente


def _construir_html_nota(seguros: List[str], empresa: Optional[str]) -> str:
    """
    Construye el HTML de la nota con los seguros seleccionados.
    Si la empresa requiere expediente (como Sindicato), se omite Negocio__c
    del lead y se indica en la nota para evitar la regla de validación.
    """
    partes = ["<ul>"]

    if empresa and _requiere_expediente(empresa):
        partes.append(
            f"<b>Negocio: {empresa}</b>"
        )

    for s in seguros:
        partes.append(f"<li>{s}</li>")

    partes.append("</ul>")
    return "".join(partes)


# ─── Orquestador principal ────────────────────────────────────────

def crear_lead_campo(
    request: CreateLeadCampoRequest,
    sf: Salesforce
) -> Tuple[str, str, str, Optional[str], Optional[str]]:
    """
    Crea un Lead en Salesforce desde el formulario de campo.

    Flujo:
    1. Resuelve código de empresa (STRM/BIMBO/NN) a nombre Salesforce
    2. Determina RecordTypeId según la empresa resuelta
    3. Obtiene OwnerId resolviendo el número de asesor externo
    4. Construye lead_data (omite Negocio__c si es Sindicato para evitar validación)
    5. Crea el Lead con createLead() (sf_create_data)
    6. Crea nota con seguros + negocio (si aplica) usando crear_nota_generica()

    Returns:
        Tuple (lead_id, nombre_completo, nombre_asesor, asesor_telefono, asesor_correo)
    """
    # ── 1. Resolver empresa (código frontend → nombre Salesforce) ──
    empresa_sf = _resolver_empresa(request.empresa)

    # ── 2. RecordTypeId según empresa resuelta ───────────────────
    record_type_id = _obtener_record_type_id(sf, empresa_sf)

    # ── 3. OwnerId desde asesor externo ──────────────────────────
    asesor_data = buscar_asesor_externo(request.numero_asesor, sf)
    if asesor_data is None or not asesor_data.get('Id'):
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró asesor externo con número: {request.numero_asesor}"
        )

    # Si el asesor tiene cuenta de usuario activa → el User es el owner del lead.
    # Si no → se asigna al owner de respaldo.
    OWNER_RESPALDO = '005WR000000OCCAYA4'
    user_id = verificar_cuenta_usuario(request.numero_asesor, sf)
    if user_id:
        owner_id = user_id
        print(f"Asesor {request.numero_asesor} tiene cuenta de usuario → owner asignado: {owner_id}")
    else:
        owner_id = OWNER_RESPALDO
        print(f"Asesor {request.numero_asesor} NO tiene cuenta de usuario → owner de respaldo: {owner_id}")

    nombre_asesor = asesor_data.get('Name', 'Desconocido')
    asesor_telefono = asesor_data.get('Numero_telefonico__c')
    asesor_correo = asesor_data.get('Correo_electronico__c')

    # ── 4. Construir lead_data ───────────────────────────────────
    apellido_completo = request.apellido_paterno
    if request.apellido_materno:
        apellido_completo += f" {request.apellido_materno}"

    nombre_completo = f"{request.nombre} {apellido_completo}"

    lead_data = {
        'LeadSource': 'Ofrecimiento en campo',
        'FirstName': request.nombre,
        'LastName': apellido_completo,
        'Email': request.email,
        'MobilePhone': request.telefono,
        'Fecha_de_nacimiento__c': str(request.fecha_nacimiento),
        'Genero__c': request.genero,
        'Asesor_externo__c': asesor_data['Id'],
        'OwnerId': owner_id,
        'RecordTypeId': record_type_id
    }

    # Incluir Negocio__c solo si el negocio NO requiere expediente
    # (ej. BIMBO no requiere, STRM sí requiere y se omite para evitar validación)
    if empresa_sf and not _requiere_expediente(empresa_sf):
        lead_data['Negocio__c'] = empresa_sf

    # ── 5. Crear Lead ────────────────────────────────────────────
    lead_result, _ = createLead(sf, lead_data)
    id_lead = lead_result['id']

    # ── 6. Crear nota con seguros (+ negocio si es Sindicato) ────
    html_nota = _construir_html_nota(request.seguros, empresa_sf)
    titulo_nota = f'Seguros solicitados - {nombre_completo}'
    crear_nota_generica(id_lead, sf, html_nota, titulo_nota)

    print(f"Lead de campo creado: {id_lead} - {nombre_completo}")
    return id_lead, nombre_completo, nombre_asesor, asesor_telefono, asesor_correo
