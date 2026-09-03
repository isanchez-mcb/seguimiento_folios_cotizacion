from datetime import date, timedelta
from typing import List, Optional, Tuple

from fastapi import HTTPException
from simple_salesforce import Salesforce

from app.models.schemas import CreateLeadCampoRequest
from app.services.buscarAsesorExterno import buscar_asesor_externo, verificar_cuenta_usuario
from app.services.enviar_correo import notificar_confirmacion_lead_campo
from app.services.sf_create_data import (
    LeadDuplicadoError,
    createLead,
    createOpportunity,
    crear_nota_generica,
    crearTarea,
)
from app.utils.diccionarios import negocios_lead_campo, ramos_lead_campo


# ─── Constantes ───────────────────────────────────────────────────

RECORD_TYPE_MASIVO = "Masivo"
RECORD_TYPE_NN_FISICA = "Persona física - Nuevos negocios"
RECORD_TYPE_NN_MORAL = "Persona moral - Nuevos negocios"

OWNER_RESPALDO = '005WR000000OCCAYA4'

# Días de plazo por defecto para CloseDate de la Opportunity de contingencia
DIAS_CIERRE_OPORTUNIDAD_CONTINGENCIA = 30

# Prefijos estándar de Salesforce para identificar el tipo de registro duplicado
PREFIJO_ID_ACCOUNT = "001"
PREFIJO_ID_LEAD = "00Q"


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


def _requiere_expediente(nombre_empresa: Optional[str]) -> bool:
    """
    Verifica si un negocio requiere expediente/número de colaborador según el catálogo.
    Retorna True por defecto si el negocio no está en el catálogo.
    """
    if not nombre_empresa:
        return False

    nombre_upper = nombre_empresa.strip().upper()
    for v in negocios_lead_campo.MAPEO.values():
        if v["nombre_sf"].upper() == nombre_upper:
            return v["requiere_expediente"]

    return True  # Por defecto, asumir que requiere expediente


def _resolver_ramos_y_tipo(
    empresa_sf: Optional[str],
    seguros: List[str]
) -> Tuple[List[str], str, bool]:
    """
    Determina, a partir de la empresa resuelta y los seguros seleccionados:
    - La lista de Ramos_de_interes__c (sin duplicados, según orden de selección).
    - El nombre del RecordType de Lead que corresponde.
    - Si el prospecto es de Persona moral (Nuevos negocios).

    - Empresa resuelta (STRM/BIMBO/otro código) → catálogo Masivo.
    - Empresa NN/vacía → se distingue física vs moral según coincidencia de los
      seguros recibidos con el catálogo PERSONA_MORAL_NN.
    """
    if empresa_sf:
        catalogo = ramos_lead_campo.MASIVO
        nombre_record_type = RECORD_TYPE_MASIVO
        es_moral = False
    else:
        es_moral = any(s in ramos_lead_campo.PERSONA_MORAL_NN for s in seguros)
        if es_moral:
            catalogo = ramos_lead_campo.PERSONA_MORAL_NN
            nombre_record_type = RECORD_TYPE_NN_MORAL
        else:
            catalogo = ramos_lead_campo.PERSONA_FISICA_NN
            nombre_record_type = RECORD_TYPE_NN_FISICA

    ramos: List[str] = []
    for seguro in seguros:
        ramos_seguro = catalogo.get(seguro)
        if ramos_seguro is None:
            raise HTTPException(
                status_code=400,
                detail=f"Seguro no reconocido para este tipo de negocio: '{seguro}'"
            )
        for ramo in ramos_seguro:
            if ramo not in ramos:
                ramos.append(ramo)

    return ramos, nombre_record_type, es_moral


def _obtener_record_type_id(sf: Salesforce, nombre_record_type: str, sobject_type: str = 'Lead') -> str:
    """
    Recupera el RecordTypeId por nombre y SObject, sin hardcodear el Id
    (los Ids cambian entre entornos de sandbox y producción).
    """
    query = (
        "SELECT Id FROM RecordType "
        f"WHERE SObjectType = '{sobject_type}' AND Name = '{nombre_record_type}'"
    )
    result = sf.query(query)

    if result['totalSize'] == 0:
        raise HTTPException(
            status_code=500,
            detail=f"No se encontró RecordType '{nombre_record_type}' para {sobject_type}"
        )

    return result['records'][0]['Id']


def _construir_html_nota(seguros: List[str], empresa: Optional[str]) -> str:
    """
    Construye el HTML de la nota con el negocio (si aplica) y los seguros seleccionados.
    """
    partes = ["<ul>"]

    if empresa:
        partes.append(f"<li><b>Negocio:</b> {empresa}</li>")

    for s in seguros:
        partes.append(f"<li>{s}</li>")

    partes.append("</ul>")
    return "".join(partes)


def _construir_descripcion_tarea(
    nombre_completo: str,
    telefono: str,
    email: str,
    empresa: Optional[str],
    seguros: List[str]
) -> str:
    """Construye la descripción de la tarea de seguimiento asociada al prospecto."""
    lineas = [
        f"Prospecto de campo: {nombre_completo}",
        f"Teléfono: {telefono}",
        f"Correo: {email}",
    ]
    if empresa:
        lineas.append(f"Negocio: {empresa}")
    lineas.append(f"Seguros de interés: {', '.join(seguros)}")
    return "\n".join(lineas)


def _construir_html_nota_oportunidad(request: CreateLeadCampoRequest, seguros: List[str]) -> str:
    """Nota de la Opportunity de contingencia: contacto + seguros de interés."""
    partes = ["<ul>"]
    partes.append(f"<li><b>Contacto:</b> {request.telefono} / {request.email}</li>")
    for s in seguros:
        partes.append(f"<li>{s}</li>")
    partes.append("</ul>")
    return "".join(partes)


def _crear_oportunidad_contingencia(
    request: CreateLeadCampoRequest,
    sf: Salesforce,
    account_id: str,
    asesor_data: dict,
    owner_id: str,
    nombre_completo: str,
    ramos: List[str]
) -> str:
    """
    Contingencia cuando el cliente ya existe en Salesforce (expediente/correo duplicado
    detectado al intentar crear el Lead): se crea una Opportunity sobre la cuenta ya
    existente en vez del Lead, con nota y tarea de seguimiento asociadas.
    """
    record_type_id = _obtener_record_type_id(sf, RECORD_TYPE_MASIVO, sobject_type='Opportunity')
    close_date = (date.today() + timedelta(days=DIAS_CIERRE_OPORTUNIDAD_CONTINGENCIA)).isoformat()

    oportunidad_data = {
        'Name': f'Código QR - {nombre_completo}',
        'AccountId': account_id,
        'OwnerId': owner_id,
        'StageName': 'Nueva',
        'CloseDate': close_date,
        'Origen_de_oportunidad__c': 'Venta en Campo',
        'RecordTypeId': record_type_id,
        'Asesor_externo__c': asesor_data['Id'],
    }
    if ramos:
        oportunidad_data['Ramos_de_interes__c'] = ';'.join(ramos)

    oportunidad = createOpportunity(sf, oportunidad_data)
    id_oportunidad = oportunidad['id']

    html_nota = _construir_html_nota_oportunidad(request, request.seguros)
    crear_nota_generica(id_oportunidad, sf, html_nota, f'Seguros solicitados - {nombre_completo}')

    descripcion_tarea = _construir_descripcion_tarea(
        nombre_completo, request.telefono, request.email, None, request.seguros
    )
    crearTarea(sf, id_oportunidad, owner_id, descripcion_tarea, usar_what_id=True)

    print(f"Cliente ya existente detectado, oportunidad creada: {id_oportunidad} - {nombre_completo}")
    return id_oportunidad


def _construir_descripcion_tarea_lead_duplicado(
    request: CreateLeadCampoRequest,
    nombre_completo: str,
    empresa_sf: Optional[str]
) -> str:
    """Descripción de la tarea de seguimiento cuando ya existe un Lead con estos datos."""
    lineas = [
        "Ya existe un prospecto registrado con estos datos (Código QR):",
        f"Nombre: {nombre_completo}",
        f"Teléfono: {request.telefono}",
        f"Correo: {request.email}",
    ]
    if empresa_sf:
        lineas.append(f"Negocio: {empresa_sf}")
    if request.expediente_colaborador:
        lineas.append(f"Expediente/colaborador: {request.expediente_colaborador}")
    if request.company:
        lineas.append(f"Company: {request.company}")
    lineas.append(f"Seguros de interés: {', '.join(request.seguros)}")
    lineas.append(f"Número de asesor: {request.numero_asesor}")
    return "\n".join(lineas)


def _crear_tarea_lead_existente(
    request: CreateLeadCampoRequest,
    sf: Salesforce,
    lead_id_existente: str,
    owner_id: str,
    nombre_completo: str,
    empresa_sf: Optional[str]
) -> str:
    """
    Contingencia cuando ya existe un Lead/prospecto con estos datos: no se duplica el
    prospecto, solo se crea una tarea de seguimiento asociada al Lead ya existente,
    con los datos del nuevo request que provocó el duplicado.
    """
    descripcion_tarea = _construir_descripcion_tarea_lead_duplicado(request, nombre_completo, empresa_sf)
    crearTarea(sf, lead_id_existente, owner_id, descripcion_tarea)

    print(f"Prospecto ya existente detectado, tarea de seguimiento creada sobre Lead: {lead_id_existente}")
    return lead_id_existente


# ─── Orquestador principal ────────────────────────────────────────

def crear_lead_campo(
    request: CreateLeadCampoRequest,
    sf: Salesforce
) -> Tuple[str, str, str, Optional[str], Optional[str]]:
    """
    Crea un Lead en Salesforce desde el formulario de campo.

    Flujo:
    1. Resuelve código de empresa (STRM/BIMBO/NN) a nombre Salesforce
    2. Resuelve Ramos_de_interes__c y el RecordType (Masivo / Persona física
       - Nuevos negocios / Persona moral - Nuevos negocios) según empresa y seguros
    3. Valida expediente_colaborador (si el negocio lo requiere) y company (si es moral)
    4. Obtiene OwnerId: para Masivo, el usuario del asesor externo (o el de respaldo si
       no tiene cuenta activa); para Nuevos negocios (física o moral), siempre el de respaldo
    5. Crea el Lead con createLead() (sin reintento silencioso ante expediente duplicado)
    6. Crea nota con seguros + negocio (si aplica) usando crear_nota_generica()
    7. Crea tarea de seguimiento asociada al owner del prospecto

    Returns:
        Tuple (lead_id, nombre_completo, nombre_asesor, asesor_telefono, asesor_correo)
    """
    # ── 1. Resolver empresa (código frontend → nombre Salesforce) ──
    empresa_sf = _resolver_empresa(request.empresa)

    # ── 2. Ramos de interés y RecordType según empresa y seguros ──
    ramos, nombre_record_type, es_moral = _resolver_ramos_y_tipo(empresa_sf, request.seguros)
    record_type_id = _obtener_record_type_id(sf, nombre_record_type)

    # ── 3. Validaciones condicionales de campos ───────────────────
    if empresa_sf and _requiere_expediente(empresa_sf) and not request.expediente_colaborador:
        raise HTTPException(
            status_code=400,
            detail="El campo 'expediente_colaborador' es requerido para el negocio seleccionado"
        )

    if es_moral and not request.company:
        raise HTTPException(
            status_code=400,
            detail="El campo 'company' es requerido para prospectos de persona moral"
        )

    # ── 4. OwnerId desde asesor externo ──────────────────────────
    asesor_data = buscar_asesor_externo(request.numero_asesor, sf)
    if asesor_data is None or not asesor_data.get('Id'):
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró asesor externo con número: {request.numero_asesor}"
        )

    if empresa_sf:
        # Masivo: si el asesor tiene cuenta de usuario activa → el User es el owner.
        # Si no → se asigna al owner de respaldo.
        user_id = verificar_cuenta_usuario(request.numero_asesor, sf)
        owner_id = user_id or OWNER_RESPALDO
        print(f"Asesor {request.numero_asesor} → owner asignado: {owner_id}")
    else:
        # Nuevos negocios (física o moral): siempre va al owner de respaldo.
        owner_id = OWNER_RESPALDO
        print(f"Prospecto de Nuevos negocios → owner de respaldo: {owner_id}")

    nombre_asesor = asesor_data.get('Name', 'Desconocido')
    asesor_telefono = asesor_data.get('Numero_telefonico__c')
    asesor_correo = asesor_data.get('Correo_electronico__c')

    # ── 5. Construir lead_data ───────────────────────────────────
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

    if empresa_sf:
        lead_data['Negocio__c'] = empresa_sf

    if request.expediente_colaborador:
        lead_data['No_expediente_No_colaborador__c'] = request.expediente_colaborador

    if es_moral:
        lead_data['Company'] = request.company

    if ramos:
        lead_data['Ramos_de_interes__c'] = ';'.join(ramos)

    # ── 6. Crear Lead ────────────────────────────────────────────
    # Sin reintento silencioso: si Salesforce detecta un duplicado, se resuelve según
    # el tipo de registro encontrado, en vez de reintentar y crear un Lead de todas formas:
    #   - Ya es cliente (Account existente) → se crea una Opportunity en su cuenta.
    #   - Ya existe un Lead/prospecto con estos datos → no se duplica, solo se agrega
    #     una tarea de seguimiento sobre ese Lead (se mantiene el trazado sin duplicar).
    try:
        lead_result, _ = createLead(sf, lead_data, reintentar_sin_expediente=False)
        id_resultado = lead_result['id']

        # ── 7. Crear nota con seguros (+ negocio si aplica) ───────
        html_nota = _construir_html_nota(request.seguros, empresa_sf)
        titulo_nota = f'Seguros solicitados - {nombre_completo}'
        crear_nota_generica(id_resultado, sf, html_nota, titulo_nota)

        # ── 8. Crear tarea de seguimiento asociada al owner del prospecto ──
        descripcion_tarea = _construir_descripcion_tarea(
            nombre_completo, request.telefono, request.email, empresa_sf, request.seguros
        )
        crearTarea(sf, id_resultado, owner_id, descripcion_tarea)

        print(f"Lead de campo creado: {id_resultado} - {nombre_completo}")
    except LeadDuplicadoError as dup:
        if dup.record_id and dup.record_id.startswith(PREFIJO_ID_ACCOUNT):
            id_resultado = _crear_oportunidad_contingencia(
                request, sf, dup.record_id, asesor_data, owner_id, nombre_completo, ramos
            )
        elif dup.record_id and dup.record_id.startswith(PREFIJO_ID_LEAD):
            id_resultado = _crear_tarea_lead_existente(
                request, sf, dup.record_id, owner_id, nombre_completo, empresa_sf
            )
        else:
            raise HTTPException(status_code=402, detail=dup.mensaje)

    # ── 9. Confirmar por correo al cliente que llenó el formulario ───
    # (en los tres casos: lead nuevo, oportunidad de contingencia, o tarea sobre lead existente)
    notificar_confirmacion_lead_campo(
        email_destino=request.email,
        nombre_completo=nombre_completo,
        seguros=request.seguros,
        nombre_asesor=nombre_asesor,
        telefono_asesor=asesor_telefono,
        email_asesor=asesor_correo,
    )

    return id_resultado, nombre_completo, nombre_asesor, asesor_telefono, asesor_correo
