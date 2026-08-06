from typing import Optional, Dict, Any, Tuple

from simple_salesforce import Salesforce


# ─── Constantes ───────────────────────────────────────────────────

#Sandbox
#CAMPAÑA_ZUMPANGO_TELEMARKETING = "701ct000013a5WsAAI"  # Sandbox
#CAMPAÑA_ZUMPANGO_PATRIMONIAL = "701Hp000001XfwQIAS"     # Sandbox

#Produccion
CAMPAÑA_ZUMPANGO_TELEMARKETING = "701WR00001coz8NYAQ"  # Sandbox
CAMPAÑA_ZUMPANGO_PATRIMONIAL = "701WR00001cjxlaYAA"     # Sandbox


COLA_ZUMPANGO_TELEMARKETING = "Zumpango Telemarketing"
COLA_ZUMPANGO_PATRIMONIAL = "Zumpango Patrimonial"
COLA_ASESOR_TELEMARKETING = "Asesor_Telemarketing"

#OWNER_TAREA_RESPALDO = '005ct00000BdIOYAA3' #Sandbox
OWNER_TAREA_RESPALDO = '005WR000008PRlCYAW' #Prod


# ─── Helpers ──────────────────────────────────────────────────────

def verificar_cuenta_usuario(numero_asesor: str, sf: Salesforce) -> Optional[str]:
    """
    Corrobora si el asesor tiene una cuenta de usuario (User) activa en Salesforce.
    
    Args:
        numero_asesor: Número de asesor (corresponde al campo Alias del User).
        sf: Instancia autenticada de Salesforce.
    
    Returns:
        El Id del User si existe un usuario activo con ese Alias, o None si no.
    """
    try:
        query = (
            "SELECT Id, Name, Alias, IsActive, Email "
            "FROM User "
            f"WHERE IsActive = True AND Alias = '{numero_asesor}'"
        )
        result = sf.query(query)
        if result['totalSize'] > 0:
            return result['records'][0]['Id']
        return None
    except Exception as e:
        print(f"Error al verificar cuenta de usuario para asesor {numero_asesor}: {e}")
        return None


def buscar_asesor_externo(numero_asesor: str, sf: Salesforce) -> Optional[Dict[str, Any]]:
    """
    Consulta un asesor externo por su número de asesor en Salesforce.
    
    Si existen múltiples registros con el mismo número, retorna el de
    fecha de creación (CreatedDate) más reciente.
    
    Args:
        numero_asesor: Número de asesor a buscar.
        sf: Instancia autenticada de Salesforce.
    
    Returns:
        Dict con los campos del asesor externo, o None si no se encuentra.
    """
    try:
        query = (
            "SELECT Id, Name, Numero_de_asesor__c, Puesto__c, Zona__c, "
            "Correo_electronico__c, Numero_telefonico__c "
            "FROM Asesor_externo__c "
            f"WHERE Numero_de_asesor__c = {numero_asesor} "
            "ORDER BY CreatedDate DESC"
        )
        result = sf.query(query)

        if result['totalSize'] == 0:
            return None

        record = result['records'][0]
        record.pop('attributes', None)
        return record

    except Exception as e:
        print(f"Error al buscar asesor externo: {e}")
        return None


def usuario_en_cola(user_id: str, nombre_cola: str, sf: Salesforce) -> bool:
    """
    Verifica si un usuario (User) pertenece a una cola (Group) en Salesforce.
    
    Args:
        user_id: ID del usuario.
        nombre_cola: Nombre de la cola.
        sf: Instancia autenticada de Salesforce.
    
    Returns:
        True si el usuario está en la cola, False en caso contrario.
    """
    try:
        query = (
            "SELECT UserOrGroupId FROM GroupMember "
            f"WHERE Group.Name = '{nombre_cola}' AND UserOrGroupId = '{user_id}'"
        )
        result = sf.query(query)
        return result['totalSize'] > 0
    except Exception as e:
        print(f"Error al verificar usuario {user_id} en cola '{nombre_cola}': {e}")
        return False


def _obtener_cola_id(nombre_cola: str, sf: Salesforce) -> Optional[str]:
    """
    Obtiene el Id de una cola desde Salesforce por su nombre.
    Las colas se almacenan en el objeto Group con Type = 'Queue'.
    
    Args:
        nombre_cola: Nombre de la cola.
        sf: Instancia autenticada de Salesforce.
    
    Returns:
        Id de la cola, o None si no se encuentra.
    """
    try:
        query = (
            "SELECT Id FROM Group "
            f"WHERE Type = 'Queue' AND Name = '{nombre_cola}'"
        )
        result = sf.query(query)
        if result['totalSize'] == 0:
            print(f"Cola '{nombre_cola}' no encontrada.")
            return None
        return result['records'][0]['Id']
    except Exception as e:
        print(f"Error al buscar cola '{nombre_cola}': {e}")
        return None


# ─── Resolución central ───────────────────────────────────────────

def resolver_campana_y_cola(
    numero_asesor: Optional[str],
    tiene_expediente: bool,
    sf: Salesforce
) -> Tuple[str, Optional[str], Optional[str], Optional[str], bool]:
    """
    Resuelve la campaña, cola, owner y asesor externo según la lógica de negocio.
    
    Casos:
    1. Asesor externo + cuenta User:
       - User en cola "Asesor Telemarketing" → Zumpango Telemarketing
       - User NO en cola → Zumpango Patrimonial
       - Owner = User del asesor, Asesor_externo__c = ID asesor, tarea owner = User
    2. Asesor externo + SIN cuenta User:
       - Usar Puesto__c del Asesor_externo__c: si contiene "Telemarketing" → Zumpango Telemarketing
       - Si no → Zumpango Patrimonial
       - Owner = cola correspondiente, Asesor_externo__c = ID asesor
       - Tarea: solo si Telemarketing, owner = cola Zumpango Telemarketing
    3. Cuenta User + SIN asesor externo:
       - User en cola "Asesor Telemarketing" → Zumpango Telemarketing, si no → Zumpango Patrimonial
       - Owner = User, NO se llena Asesor_externo__c, tarea owner = User
    4. Sin asesor ni cuenta:
       - Con expediente → Zumpango Telemarketing, cola owner, tarea respaldo
       - Sin expediente → Zumpango Patrimonial, cola owner, sin tarea
    
    Args:
        numero_asesor: Número de asesor (puede ser None o vacío).
        tiene_expediente: True si el prospecto tiene expediente (telefonista),
                          False si no (familiar).
        sf: Instancia autenticada de Salesforce.
    
    Returns:
        Tuple (campaign_id, owner_id, asesor_externo_id, nombre_asesor, crear_tarea)
        
        - campaign_id: ID de la campaña Zumpango Telemarketing o Patrimonial.
        - owner_id: ID del User del asesor, o ID de la cola, o None.
        - asesor_externo_id: ID del registro Asesor_externo__c, o None.
        - nombre_asesor: Nombre del asesor externo, o None.
        - crear_tarea: True si se debe crear tarea, False si no.
    """
    asesor_externo_id = None
    nombre_asesor = None
    owner_id = None
    crear_tarea = False

    # ── Determinar si hay número de asesor ───────────────────────
    tiene_asesor = bool(numero_asesor and numero_asesor.strip())

    if tiene_asesor:
        # Buscar asesor externo
        asesor_data = buscar_asesor_externo(numero_asesor.strip(), sf)
        user_id = verificar_cuenta_usuario(numero_asesor.strip(), sf)

        if asesor_data and asesor_data.get('Id'):
            asesor_externo_id = asesor_data['Id']
            nombre_asesor = asesor_data.get('Name', 'Desconocido')

            if user_id:
                # ── Caso 1: Asesor externo + cuenta User ─────────
                if usuario_en_cola(user_id, COLA_ASESOR_TELEMARKETING, sf):
                    campaign_id = CAMPAÑA_ZUMPANGO_TELEMARKETING
                    owner_id = user_id
                    crear_tarea = True
                    print(f"Asesor {numero_asesor} en cola Asesor Telemarketing → campaña Zumpango Telemarketing")
                else:
                    campaign_id = CAMPAÑA_ZUMPANGO_PATRIMONIAL
                    owner_id = user_id
                    crear_tarea = True
                    print(f"Asesor {numero_asesor} NO en cola Asesor Telemarketing → campaña Zumpango Patrimonial")
            else:
                # ── Caso 2: Asesor externo + SIN cuenta User ─────
                # Usar Puesto__c del asesor externo para determinar campaña
                puesto = asesor_data.get('Puesto__c', '') or ''
                if "Telemarketing" in puesto:
                    campaign_id = CAMPAÑA_ZUMPANGO_TELEMARKETING
                    owner_id = _obtener_cola_id(COLA_ZUMPANGO_TELEMARKETING, sf)
                    crear_tarea = True
                    print(f"Asesor {numero_asesor} sin cuenta User, Puesto='{puesto}' → campaña Zumpango Telemarketing")
                else:
                    campaign_id = CAMPAÑA_ZUMPANGO_PATRIMONIAL
                    owner_id = _obtener_cola_id(COLA_ZUMPANGO_PATRIMONIAL, sf)
                    crear_tarea = False
                    print(f"Asesor {numero_asesor} sin cuenta User, Puesto='{puesto}' → campaña Zumpango Patrimonial")
        elif user_id:
            # ── Caso 3: Cuenta User + SIN asesor externo ─────────
            # Se asigna al User como owner, pero NO se llena Asesor_externo__c
            if usuario_en_cola(user_id, COLA_ASESOR_TELEMARKETING, sf):
                campaign_id = CAMPAÑA_ZUMPANGO_TELEMARKETING
                owner_id = user_id
                crear_tarea = True
                print(f"User {numero_asesor} (sin asesor externo) en cola Asesor Telemarketing → campaña Zumpango Telemarketing")
            else:
                campaign_id = CAMPAÑA_ZUMPANGO_PATRIMONIAL
                owner_id = user_id
                crear_tarea = True
                print(f"User {numero_asesor} (sin asesor externo) NO en cola Asesor Telemarketing → campaña Zumpango Patrimonial")
        else:
            # ── Caso 4: No existe asesor ni cuenta ───────────────
            print(f"Asesor {numero_asesor} no encontrado ni en Asesor_externo__c ni en User. Se trata como sin asesor.")
            tiene_asesor = False

    if not tiene_asesor:
        # ── Caso 4: Sin asesor ni cuenta ─────────────────────────
        if tiene_expediente:
            campaign_id = CAMPAÑA_ZUMPANGO_TELEMARKETING
            owner_id = _obtener_cola_id(COLA_ZUMPANGO_TELEMARKETING, sf)
            crear_tarea = True
            print("Sin asesor + expediente → campaña Zumpango Telemarketing, tarea con owner respaldo")
        else:
            campaign_id = CAMPAÑA_ZUMPANGO_PATRIMONIAL
            owner_id = _obtener_cola_id(COLA_ZUMPANGO_PATRIMONIAL, sf)
            crear_tarea = False
            print("Sin asesor + sin expediente → campaña Zumpango Patrimonial, sin tarea")

    return campaign_id, owner_id, asesor_externo_id, nombre_asesor, crear_tarea
