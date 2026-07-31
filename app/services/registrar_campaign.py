import re
from typing import List, Optional, Tuple

from fastapi import HTTPException
from simple_salesforce import Salesforce

from app.models.schemas import RegistroCampaignRequest
from app.services.crearCortizacion import normalizar_telefono
from app.services.sf_create_data import createCampaignMember, createLead, crear_nota_generica, obtener_record_type_id


# ─── Constantes ───────────────────────────────────────────────────

CAMPAIGN_ID = "701ct000013a5WsAAI" #Sandbox
#CAMPAIGN_ID = "701WR00001cl3SKYAY" #Produccion

QUEUE_NAME = "Prospectos Telemarketing"

# ─── Helpers ──────────────────────────────────────────────────────

def _es_verdadero(valor) -> bool:
    """Retorna True si el valor de Salesforce se considera verdadero."""
    if valor is None:
        return False
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "1", "yes")
    return bool(valor)


def _generar_variaciones_expediente(expediente: str) -> List[str]:
    """
    Genera todas las variaciones del expediente quitando ceros a la izquierda.
    
    Ejemplo: "00017" → ["0017", "017", "17"]
    Límite natural: hasta que el string deje de comenzar con '0'.
    """
    variaciones = []
    limpio = expediente.strip()
    while limpio.startswith("0") and len(limpio) > 1:
        limpio = limpio[1:]  # Quitar un cero
        variaciones.append(limpio)
    return variaciones


def _buscar_cuenta_por_expediente(
    sf: Salesforce,
    expediente: str,
    negocio: str
) -> Optional[dict]:
    """
    Busca una cuenta por No_expediente_No_colaborador__c.
    
    Estrategia en cascada:
    1. Busca con el expediente exacto + negocio
    2. Si no encuentra, itera variaciones (quitando ceros) + negocio
    3. Si aún no, itera variaciones sin importar el negocio
    
    Retorna el registro de Account si encuentra, o None si no.
    """
    # ── Intento 1: expediente exacto ─────────────────────────────
    query = (
        "SELECT Id, Name, No_expediente_No_colaborador__c, "
        "PersonEmail, PersonMobilePhone, Cuenta_verificada__c, Negocio__c "
        "FROM Account "
        f"WHERE No_expediente_No_colaborador__c = '{expediente}'"
    )
    result = sf.query(query)
    if result['totalSize'] > 0:
        return result['records'][0]

    # ── Intento 2: variaciones + negocio ─────────────────────────
    variaciones = _generar_variaciones_expediente(expediente)
    for var in variaciones:
        query = (
            "SELECT Id, Name, No_expediente_No_colaborador__c, "
            "PersonEmail, PersonMobilePhone, Cuenta_verificada__c, Negocio__c "
            "FROM Account "
            f"WHERE No_expediente_No_colaborador__c = '{var}' "
            f"AND Negocio__c = '{negocio}'"
        )
        result = sf.query(query)
        if result['totalSize'] > 0:
            print(f"Cuenta encontrada con variación '{var}' + negocio coincidente")
            return result['records'][0]

    # ── Intento 3: variaciones sin negocio ───────────────────────
    for var in variaciones:
        query = (
            "SELECT Id, Name, No_expediente_No_colaborador__c, "
            "PersonEmail, PersonMobilePhone, Cuenta_verificada__c, Negocio__c "
            "FROM Account "
            f"WHERE No_expediente_No_colaborador__c = '{var}'"
        )
        result = sf.query(query)
        if result['totalSize'] > 0:
            print(f"Cuenta encontrada con variación '{var}' (negocio no coincidente)")
            return result['records'][0]

    return None


# ─── Helpers para colas ───────────────────────────────────────────

def _obtener_cola_prospectos(sf: Salesforce) -> Optional[str]:
    """
    Obtiene el Id de la cola 'Prospectos Telemarketing' desde Salesforce.
    Las colas se almacenan en el objeto Group con Type = 'Queue'.
    
    Returns:
        Id de la cola, o None si no se encuentra (se asigna al creador por defecto).
    """
    try:
        query = (
            "SELECT Id FROM Group "
            f"WHERE Type = 'Queue' AND Name = '{QUEUE_NAME}'"
        )
        result = sf.query(query)
        if result['totalSize'] == 0:
            print(f"Cola '{QUEUE_NAME}' no encontrada. Se asignará al creador por defecto.")
            return None
        queue_id = result['records'][0]['Id']
        print(f"Cola '{QUEUE_NAME}' encontrada: {queue_id}")
        return queue_id
    except Exception as e:
        print(f"Error al buscar cola '{QUEUE_NAME}': {e}. Se asignará al creador por defecto.")
        return None


# ─── Escenario 2: Crear Lead (cuenta no existe) ───────────────────

def _crear_lead_campaign(
    request: RegistroCampaignRequest,
    telefono_normalizado: str,
    sf: Salesforce,
    record_type_name: str = 'Masivo',
    negocio_forzado: Optional[str] = None
) -> Tuple[None, None, str, str, str]:
    """
    Crea un Lead en Salesforce y lo asocia a la campaña mediante CampaignId.
    
    Args:
        request: Datos del formulario.
        telefono_normalizado: Teléfono con +52.
        sf: Instancia de Salesforce.
        record_type_name: Nombre del RecordType ('Masivo' o 'Persona física - Nuevos negocios').
        negocio_forzado: Si se pasa, sobrescribe request.negocio.
    
    Returns:
        Tuple (None, None, lead_id, campaign_member_id, negocio)
    """
    # Construir LastName: apellidos, o si no hay, concatenar nombre+apellido
    # para no dejar el campo vacío
    last_name = request.apellidos or f"{request.primer_nombre or ''} {request.segundo_nombre or ''}".strip() or "Sin apellido"

    # Determinar negocio
    negocio = negocio_forzado if negocio_forzado is not None else request.negocio

    # Obtener RecordTypeId según el tipo de registro
    record_type_id = obtener_record_type_id(sf, 'Lead', record_type_name)

    # Obtener el Id de la cola para asignar el lead (si no existe, se asigna al creador)
    queue_id = _obtener_cola_prospectos(sf)

    lead_data = {
        'LeadSource': 'Sitio Web',
        'FirstName': request.primer_nombre or '',
        'MiddleName': request.segundo_nombre or '',
        'LastName': last_name,
        'Email': request.correo,
        'MobilePhone': telefono_normalizado,
        'Negocio__c': negocio,
        'Estado_de_la_republica__c': 'Ciudad de México',
        'Campana_del__c': CAMPAIGN_ID,
        'RecordTypeId': record_type_id,
    }

    # Solo incluir OwnerId si se encontró la cola
    if queue_id:
        lead_data['OwnerId'] = queue_id

    # Solo incluir expediente si existe
    if request.expediente and request.expediente.strip():
        lead_data['No_expediente_No_colaborador__c'] = request.expediente

    lead_result, _ = createLead(sf, lead_data)
    lead_id = lead_result['id']
    print(f"Lead creado para campaña: {lead_id} (RecordType: {record_type_name})")

    # Crear nota con ocupación si se proporcionó
    if request.ocupacion and request.ocupacion.strip():
        html_ocupacion = f"Ocupación: {request.ocupacion.strip()}"
        titulo_nota = f'Ocupación - {last_name}'
        nota_creada = crear_nota_generica(lead_id, sf, html_ocupacion, titulo_nota)
        if nota_creada:
            print(f"Nota de ocupación creada para lead {lead_id}")
        else:
            print(f"ERROR: No se pudo crear la nota de ocupación para lead {lead_id}")

    # El CampaignMember se crea automáticamente al asignar CampaignId en el Lead
    # Retornamos el lead_id como identificador
    return None, None, lead_id, "LEAD_CREADO", negocio


# ─── Orquestador principal ────────────────────────────────────────

def registrar_en_campaign(
    request: RegistroCampaignRequest,
    sf: Salesforce
) -> Tuple[Optional[str], Optional[str], Optional[str], str, str]:
    """
    Registra un prospecto en una campaña de Salesforce.

    Flujo:
    1. Normaliza el teléfono (agrega +52 si no lo tiene)
    2. Busca la cuenta (Account) por No_expediente_No_colaborador__c
       con búsqueda en cascada (expediente exacto → variaciones + negocio → variaciones solas)
       incluyendo PersonEmail, PersonMobilePhone, Cuenta_verificada__c, Negocio__c
    3. Si encuentra cuenta → Escenario 1: actualiza datos y crea CampaignMember
    4. Si NO encuentra cuenta → Escenario 2: crea Lead con CampaignId

    Returns:
        Tuple (account_id, contact_id, lead_id, campaign_member_id, negocio)
    """
    # ── 1. Normalizar teléfono ───────────────────────────────────
    telefono_normalizado = normalizar_telefono(request.telefono)

    # ── 2. Detectar si viene sin expediente ──────────────────────
    if not request.expediente or not request.expediente.strip():
        # ── ESCENARIO 3: Sin expediente → Lead como Nuevos Negocios ──
        print("Sin expediente. Creando lead como Nuevos Negocios...")
        return _crear_lead_campaign(
            request, telefono_normalizado, sf,
            record_type_name='Persona física - Nuevos negocios',
            negocio_forzado='NUEVOS NEGOCIOS'
        )

    # ── 3. Buscar cuenta con búsqueda en cascada ─────────────────
    account = _buscar_cuenta_por_expediente(sf, request.expediente, request.negocio)

    if account is None:
        # ── ESCENARIO 2: No existe cuenta → crear Lead ───────────
        print("Cuenta no encontrada. Creando lead para campaña...")
        return _crear_lead_campaign(request, telefono_normalizado, sf)

    account_id = account['Id']
    print(f"Cuenta encontrada: {account_id} - {account.get('Name', '')}")

    # ── 3. Construir update_data condicional ─────────────────────
    update_data = {
        'Email_landing_page__c': request.correo,
        'Phone': telefono_normalizado,
    }

    # PersonEmail: solo si está vacío
    person_email_actual = account.get('PersonEmail')
    if not person_email_actual:
        update_data['PersonEmail'] = request.correo
        print("PersonEmail vacío → se rellena con el correo del usuario")

    # PersonMobilePhone: solo si está vacío
    person_phone_actual = account.get('PersonMobilePhone')
    if not person_phone_actual:
        update_data['PersonMobilePhone'] = telefono_normalizado
        print("PersonMobilePhone vacío → se rellena con el teléfono del usuario")

    # Cuenta_verificada__c: si es false/vacío → true
    cuenta_verificada = account.get('Cuenta_verificada__c')
    if not _es_verdadero(cuenta_verificada):
        update_data['Cuenta_verificada__c'] = True
        print("Cuenta_verificada__c en false → se pasa a true")

    # Negocio__c: solo si está vacío
    negocio_actual = account.get('Negocio__c')
    if not negocio_actual:
        update_data['Negocio__c'] = request.negocio
        print("Negocio__c vacío → se rellena con el negocio del usuario")

    # ── 4. Ejecutar actualización ────────────────────────────────
    try:
        sf.Account.update(account_id, update_data)
        campos_actualizados = ", ".join(update_data.keys())
        print(f"Cuenta {account_id} actualizada: {campos_actualizados}")

    except Exception as e:
        error_str = str(e)
        print(f"Error al actualizar cuenta {account_id}: {error_str}")

        # ── 4a. Reintento si es duplicado de PersonEmail ─────────
        # Si el correo ya está registrado en otra cuenta, Salesforce
        # dispara DUPLICATES_DETECTED. En ese caso, eliminamos PersonEmail
        # del update_data (lo dejamos vacío como estaba) y reintentamos.
        # Email_landing_page__c y Phone se actualizan igual.
        if "DUPLICATES_DETECTED" in error_str and "Email" in error_str:
            print("Duplicado de PersonEmail detectado. "
                  "Eliminando PersonEmail del update_data y reintentando...")

            update_data.pop('PersonEmail', None)

            try:
                sf.Account.update(account_id, update_data)
                campos_actualizados = ", ".join(update_data.keys())
                print(f"Cuenta {account_id} actualizada sin PersonEmail: {campos_actualizados}")
            except Exception as retry_e:
                print(f"Error en reintento sin PersonEmail: {retry_e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Error al actualizar la cuenta incluso después de omitir PersonEmail: {str(retry_e)}"
                )

        # ── 4b. Reintento si es validación del expediente ────────
        elif "FIELD_CUSTOM_VALIDATION_EXCEPTION" in error_str and "No_expediente_No_colaborador__c" in error_str:
            print("Regla de validación de expediente detectada. "
                  "Reintentando con Negocio__c y No_expediente_No_colaborador__c del formulario...")

            # Forzar Negocio__c y No_expediente con los valores limpios del formulario
            # para que las reglas de validación (RV_03, RV_04, RV_05, RV_09, RV_10)
            # coincidan con la longitud correcta del expediente
            update_data['No_expediente_No_colaborador__c'] = request.expediente
            update_data['Negocio__c'] = request.negocio

            expediente_bd = account.get('No_expediente_No_colaborador__c', '')
            if expediente_bd and expediente_bd != request.expediente:
                print(f"Expediente en BD '{expediente_bd}' será corregido a '{request.expediente}'")

            try:
                sf.Account.update(account_id, update_data)
                campos_actualizados = ", ".join(update_data.keys())
                print(f"Cuenta {account_id} actualizada en reintento: {campos_actualizados}")

            except Exception as retry_e:
                retry_error_str = str(retry_e)
                print(f"Error en reintento de actualización: {retry_error_str}")

                # Si en el reintento también salta duplicado de email, quitarlo y reintentar
                if "DUPLICATES_DETECTED" in retry_error_str and "Email" in retry_error_str:
                    print("Duplicado de PersonEmail en reintento. Eliminando PersonEmail y reintentando...")
                    update_data.pop('PersonEmail', None)

                    try:
                        sf.Account.update(account_id, update_data)
                        campos_actualizados = ", ".join(update_data.keys())
                        print(f"Cuenta {account_id} actualizada en segundo reintento: {campos_actualizados}")
                    except Exception as retry2_e:
                        print(f"Error en segundo reintento: {retry2_e}")
                        raise HTTPException(
                            status_code=500,
                            detail=f"Error al actualizar la cuenta incluso después de corregir expediente y email: {str(retry2_e)}"
                        )
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Error al actualizar la cuenta incluso después de corregir expediente y negocio: {str(retry_error_str)}"
                    )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Error al actualizar la cuenta: {str(error_str)}"
            )

    # ── 5. Buscar contacto asociado a la cuenta ──────────────────
    query_contact = (
        "SELECT Id, Name, Email FROM Contact "
        f"WHERE AccountId = '{account_id}' "
        "ORDER BY CreatedDate DESC"
    )
    result_contact = sf.query(query_contact)

    if result_contact['totalSize'] == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró contacto asociado a la cuenta: {account_id}"
        )

    contact = result_contact['records'][0]
    contact_id = contact['Id']
    print(f"Contacto encontrado: {contact_id} - {contact.get('Name', '')}")

    # ── 6. Crear CampaignMember ──────────────────────────────────
    member_data = {
        'ContactId': contact_id,
        'CampaignId': CAMPAIGN_ID,
        'Status': 'Registrado',
    }

    try:
        campaign_member_id = createCampaignMember(sf, member_data)
        print(f"CampaignMember creado: {campaign_member_id}")

    except Exception as e:
        error_str = str(e)
        # Si ya era miembro de campaña, no es un error real.
        # La cuenta ya se actualizó correctamente.
        if "DUPLICATE_VALUE" in error_str and "Ya es un miembro de campaña" in error_str:
            print("El contacto ya es miembro de la campaña")
            campaign_member_id = "EXISTENTE"
        else:
            print(f"Error al crear CampaignMember: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error al crear el miembro de campaña: {str(e)}"
            )

    print(
        f"Registro en campaña completado: "
        f"account={account_id}, contact={contact_id}, "
        f"campaign_member={campaign_member_id}"
    )
    return account_id, contact_id, None, campaign_member_id, request.negocio