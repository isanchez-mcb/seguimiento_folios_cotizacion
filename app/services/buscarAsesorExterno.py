from simple_salesforce import Salesforce
from typing import Optional, Dict, Any


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


def _normalizar_valor(valor) -> Optional[str]:
    """Convierte cualquier valor Salesforce a string o None."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        # Evitar decimales: 10056.0 -> "10056"
        if isinstance(valor, float) and valor == int(valor):
            return str(int(valor))
        return str(valor)
    if isinstance(valor, bool):
        return str(valor).lower()
    return str(valor)


def buscar_asesor_externo(numero_asesor: str, sf: Salesforce) -> Optional[Dict[str, Any]]:
    """
    Consulta un asesor externo por su número de asesor en Salesforce.
    
    Si existen múltiples registros con el mismo número, retorna el de
    fecha de creación (CreatedDate) más reciente.
    
    Args:
        numero_asesor: Número de asesor a buscar.
        sf: Instancia autenticada de Salesforce.
    
    Returns:
        Dict con todos los campos como strings, o None si no se encuentra.
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

        # Tomar el primer registro (el más reciente por ORDER BY CreatedDate DESC)
        record = result['records'][0]
        record.pop('attributes', None)

        # Normalizar todos los campos a string para que coincidan con el modelo Pydantic
        record_normalizado = {
            campo: _normalizar_valor(valor)
            for campo, valor in record.items()
        }

        return record_normalizado

    except Exception as e:
        print(f"Error al buscar asesor externo: {e}")
        raise
