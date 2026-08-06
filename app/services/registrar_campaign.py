import re
from typing import List, Optional, Tuple

from fastapi import HTTPException
from simple_salesforce import Salesforce

from app.models.schemas import RegistroCampaignRequest
from app.services.asesor_campana import (
    CAMPAÑA_ZUMPANGO_TELEMARKETING,
    CAMPAÑA_ZUMPANGO_PATRIMONIAL,
    COLA_ZUMPANGO_TELEMARKETING,
    COLA_ZUMPANGO_PATRIMONIAL,
    OWNER_TAREA_RESPALDO,
    resolver_campana_y_cola,
)
from app.services.crearCortizacion import normalizar_telefono
from app.services.sf_create_data import createCampaignMember, createLead, crear_nota_generica, crear_tarea_campana, obtener_record_type_id


# ─── Constantes de validación de empresa por tamaño ───────────────

MAPEO_EMPRESA_POR_TAMANO = {
    5: "CAJA DE AHORRO DE LOS TELEFONISTAS, S.C DE A.P. DE R.L. DE C.V.",
    6: "EMPLEADOS DEL STRM",
    7: "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA",
    8: "COMPAÑÍA DE TELÉFONOS Y BIENES RAÍCES, S.A. DE C.V.",
}


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


def _generar_variaciones_con_ceros(expediente: str, max_digitos: int = 8) -> List[str]:
    """
    Genera variaciones del expediente agregando ceros a la izquierda.
    
    Ejemplo: "35" → ["035", "0035", "00035", "000035", "0000035", "00000035"]
    
    Args:
        expediente: Expediente ingresado por el usuario.
        max_digitos: Longitud máxima a la que se pueden rellenar ceros.
    
    Returns:
        Lista de variaciones con ceros agregados a la izquierda.
    """
    variaciones = []
    limpio = expediente.strip()
    if not limpio:
        return variaciones

    # Agregar ceros a la izquierda hasta alcanzar max_digitos
    for i in range(1, max_digitos - len(limpio) + 1):
        variaciones.append(limpio.zfill(len(limpio) + i))
    return variaciones


def _buscar_cuenta_por_expediente(
    sf: Salesforce,
    expediente: str,
    negocio: str
) -> Optional[dict]:
    """
    Busca una cuenta por No_expediente_No_colaborador__c.
    
    Estrategia en cascada:
    1. Busca con el expediente exacto
    2. Si no encuentra, itera variaciones (quitando ceros) + negocio
    3. Si aún no, itera variaciones sin importar el negocio
    4. Luego itera variaciones (agregando ceros a la izquierda) + negocio
    5. Finalmente itera variaciones (agregando ceros) sin importar el negocio
    
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

    # ── Intento 4: variaciones agregando ceros + negocio ────────
    variaciones_ceros = _generar_variaciones_con_ceros(expediente)
    for var in variaciones_ceros:
        query = (
            "SELECT Id, Name, No_expediente_No_colaborador__c, "
            "PersonEmail, PersonMobilePhone, Cuenta_verificada__c, Negocio__c "
            "FROM Account "
            f"WHERE No_expediente_No_colaborador__c = '{var}' "
            f"AND Negocio__c = '{negocio}'"
        )
        result = sf.query(query)
        if result['totalSize'] > 0:
            print(f"Cuenta encontrada con variación '{var}' (agregando ceros) + negocio coincidente")
            return result['records'][0]

    # ── Intento 5: variaciones agregando ceros sin negocio ──────
    for var in variaciones_ceros:
        query = (
            "SELECT Id, Name, No_expediente_No_colaborador__c, "
            "PersonEmail, PersonMobilePhone, Cuenta_verificada__c, Negocio__c "
            "FROM Account "
            f"WHERE No_expediente_No_colaborador__c = '{var}'"
        )
        result = sf.query(query)
        if result['totalSize'] > 0:
            print(f"Cuenta encontrada con variación '{var}' (agregando ceros, negocio no coincidente)")
            return result['records'][0]

    return None


def _resolver_empresa_por_tamano(expediente: str) -> Optional[str]:
    """
    Resuelve la empresa según el tamaño del expediente.
    
    Si el expediente es más corto que el tamaño deseado, se rellena
    con ceros a la izquierda hasta alcanzar el tamaño.
    
    Mapeo:
    - 5 → CAJA DE AHORRO DE LOS TELEFONISTAS, S.C DE A.P. DE R.L. DE C.V.
    - 6 → EMPLEADOS DEL STRM
    - 7 → SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA
    - 8 → COMPAÑÍA DE TELÉFONOS Y BIENES RAÍCES, S.A. DE C.V
    """
    if not expediente:
        return None

    expediente_limpio = expediente.strip()
    tamano = len(expediente_limpio)

    # Si el tamaño coincide exactamente con un mapeo
    if tamano in MAPEO_EMPRESA_POR_TAMANO:
        return MAPEO_EMPRESA_POR_TAMANO[tamano]

    # Si es más corto que el tamaño mínimo, rellenar con ceros a la izquierda
    # hasta alcanzar el tamaño deseado más cercano
    tamano_minimo = min(MAPEO_EMPRESA_POR_TAMANO.keys())
    if tamano < tamano_minimo:
        # Rellenar con ceros a la izquierda hasta el tamaño mínimo
        expediente_rellenado = expediente_limpio.zfill(tamano_minimo)
        return MAPEO_EMPRESA_POR_TAMANO[tamano_minimo]

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

    # ── Resolver campaña, cola, owner y asesor según la lógica ──
    tiene_expediente = bool(request.expediente and request.expediente.strip())
    campaign_id, owner_id, asesor_externo_id, nombre_asesor, crear_tarea = resolver_campana_y_cola(
        request.numero_asesor, tiene_expediente, sf
    )

    lead_data = {
        'LeadSource': 'Sitio Web',
        'FirstName': request.primer_nombre or '',
        'MiddleName': request.segundo_nombre or '',
        'LastName': last_name,
        'Email': request.correo,
        'MobilePhone': telefono_normalizado,
        'Negocio__c': negocio,
        'Estado_de_la_republica__c': 'Ciudad de México',
        'Campana_del__c': campaign_id,
        'RecordTypeId': record_type_id,
    }

    # Solo incluir OwnerId si se resolvió (cola o user)
    if owner_id:
        lead_data['OwnerId'] = owner_id

    # Asignar asesor externo si se encontró
    if asesor_externo_id:
        lead_data['Asesor_externo__c'] = asesor_externo_id
        print(f"Asesor externo asignado al lead: {asesor_externo_id}")

    # Solo incluir expediente si existe
    if request.expediente and request.expediente.strip():
        lead_data['No_expediente_No_colaborador__c'] = request.expediente

    # ── 5. Crear Lead con manejo de validación de empresa ────────
    try:
        lead_result, _ = createLead(sf, lead_data)
    except Exception as e:
        error_str = str(e)
        # Si la validación de empresa/expediente falla, resolver empresa por tamaño
        if "FIELD_CUSTOM_VALIDATION_EXCEPTION" in error_str and "No_expediente_No_colaborador__c" in error_str:
            print("Validación de empresa falló en lead. Resolviendo empresa por tamaño del expediente...")

            empresa_por_tamano = _resolver_empresa_por_tamano(request.expediente)
            if empresa_por_tamano:
                lead_data['Negocio__c'] = empresa_por_tamano

                # Rellenar expediente con ceros a la izquierda si es más corto que el mínimo
                expediente_limpio = request.expediente.strip()
                tamano = len(expediente_limpio)
                if tamano < 5:
                    lead_data['No_expediente_No_colaborador__c'] = expediente_limpio.zfill(5)
                    print(f"Expediente rellenado con ceros: {lead_data['No_expediente_No_colaborador__c']}")

                print(f"Empresa resuelta por tamaño para lead: {empresa_por_tamano}")
                lead_result, _ = createLead(sf, lead_data)
            else:
                raise
        else:
            raise

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

    # ── Crear tarea si aplica (prospecto) ────────────────────────
    if crear_tarea:
        # Determinar owner de la tarea:
        # - Caso 1/3: owner_id es User (005...) → el User del asesor
        # - Caso 2: owner_id es cola Zumpango Telemarketing → la cola
        # - Caso 4: sin asesor → owner respaldo
        if owner_id and owner_id.startswith('005'):
            owner_tarea = owner_id
        elif asesor_externo_id:
            owner_tarea = owner_id
        else:
            owner_tarea = OWNER_TAREA_RESPALDO

        descripcion_tarea = (
            f"Registro en campaña desde landing page.\n"
            f"Lead: {lead_id}"
        )
        tarea_creada = crear_tarea_campana(
            sf, lead_id, campaign_id, owner_tarea, descripcion_tarea
        )
        if tarea_creada:
            print(f"Tarea de campaña creada para lead {lead_id}")
        else:
            print(f"ERROR: No se pudo crear la tarea de campaña para lead {lead_id}")

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
    telefono_normalizado = normalizar_telefono(request.telefono) if request.telefono else ""

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
    }

    # Phone: solo si se proporcionó teléfono
    if telefono_normalizado:
        update_data['Phone'] = telefono_normalizado

    # PersonEmail: solo si está vacío
    person_email_actual = account.get('PersonEmail')
    if not person_email_actual:
        update_data['PersonEmail'] = request.correo
        print("PersonEmail vacío → se rellena con el correo del usuario")

    # PersonMobilePhone: solo si está vacío y hay teléfono
    person_phone_actual = account.get('PersonMobilePhone')
    if not person_phone_actual and telefono_normalizado:
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

            # Intento 1: forzar Negocio__c y No_expediente con los valores del formulario
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

                # ── 4b-1. Reintento por duplicado de email ───────
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

                # ── 4b-2. Último intento: resolver empresa por tamaño ──
                elif "FIELD_CUSTOM_VALIDATION_EXCEPTION" in retry_error_str and "No_expediente_No_colaborador__c" in retry_error_str:
                    print("Validación de empresa falló de nuevo. "
                          "Resolviendo empresa por tamaño del expediente...")

                    empresa_por_tamano = _resolver_empresa_por_tamano(request.expediente)
                    if empresa_por_tamano:
                        update_data['Negocio__c'] = empresa_por_tamano
                        print(f"Empresa resuelta por tamaño: {empresa_por_tamano}")

                        try:
                            sf.Account.update(account_id, update_data)
                            campos_actualizados = ", ".join(update_data.keys())
                            print(f"Cuenta {account_id} actualizada en último intento: {campos_actualizados}")
                        except Exception as retry3_e:
                            print(f"Error en último intento: {retry3_e}")
                            raise HTTPException(
                                status_code=500,
                                detail=f"Error al actualizar la cuenta incluso después de resolver empresa por tamaño: {str(retry3_e)}"
                            )
                    else:
                        raise HTTPException(
                            status_code=500,
                            detail=f"No se pudo resolver la empresa por tamaño del expediente: {request.expediente}"
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

    # ── 6. Resolver campaña, cola, owner y asesor ────────────────
    tiene_expediente = bool(request.expediente and request.expediente.strip())
    campaign_id_member, owner_id, asesor_externo_id, nombre_asesor, crear_tarea = resolver_campana_y_cola(
        request.numero_asesor, tiene_expediente, sf
    )

    member_data = {
        'ContactId': contact_id,
        'CampaignId': campaign_id_member,
        'Status': 'Registrado',
    }

    # Agregar Asesor_externo_captura__c si se encontró asesor externo
    if asesor_externo_id:
        member_data['Asesor_externo_captura__c'] = asesor_externo_id
        print(f"CampaignMember → Asesor_externo_captura__c = {asesor_externo_id}")

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

    # ── 7. Crear tarea si aplica (solo si CampaignMember es nuevo) ──
    if campaign_member_id != "EXISTENTE" and crear_tarea:
        # Determinar owner de la tarea:
        # - Caso 1/3: owner_id es User (005...) → el User del asesor
        # - Caso 2: owner_id es cola Zumpango Telemarketing → la cola
        # - Caso 4: sin asesor → owner respaldo
        if owner_id and owner_id.startswith('005'):
            owner_tarea = owner_id
        elif asesor_externo_id:
            owner_tarea = owner_id
        else:
            owner_tarea = OWNER_TAREA_RESPALDO

        descripcion_tarea = (
            f"Registro en campaña desde landing page.\n"
            f"Contacto: {contact_id}\n"
            f"Cuenta: {account_id}"
        )
        tarea_creada = crear_tarea_campana(
            sf, contact_id, campaign_id_member, owner_tarea, descripcion_tarea
        )
        if tarea_creada:
            print(f"Tarea de campaña creada para contacto {contact_id}")
        else:
            print(f"ERROR: No se pudo crear la tarea de campaña para contacto {contact_id}")

    print(
        f"Registro en campaña completado: "
        f"account={account_id}, contact={contact_id}, "
        f"campaign_member={campaign_member_id}"
    )
    return account_id, contact_id, None, campaign_member_id, request.negocio