from simple_salesforce import Salesforce

from app.models.schemas import AccountEmailChangedRequest
from app.services.sf_create_data import crear_nota_generica


def registrar_cambio_correo(request: AccountEmailChangedRequest, sf: Salesforce) -> bool:
    """
    Registra en Salesforce (como ContentNote en la Account) el cambio de PersonEmail
    recibido desde el webhook de AccountEmailTrigger / AccountWebhookQueueable.

    Returns:
        True si se creó la nota correctamente, False en caso contrario.
    """
    html_nota = (
        "<ul>"
        f"<li><b>Correo anterior:</b> {request.old_email or 'N/A'}</li>"
        f"<li><b>Correo nuevo:</b> {request.new_email or 'N/A'}</li>"
        "</ul>"
    )
    titulo = f"Cambio de correo - {request.account_name}"

    return crear_nota_generica(request.account_id, sf, html_nota, titulo)
