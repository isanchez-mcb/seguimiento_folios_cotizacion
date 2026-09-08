from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import AccountEmailChangedRequest, AccountEmailChangedResponse
from app.dependencias.sf_service import get_salesforce_data
from app.dependencias.security import verifiy_auth
from app.services.account_webhook import registrar_cambio_correo

router = APIRouter()


@router.post(
    "/webhooks/account/email-changed",
    response_model=AccountEmailChangedResponse,
    status_code=200,
    tags=["Webhooks"]
)
def account_email_changed_endpoint(
    request: AccountEmailChangedRequest,
    sf=Depends(get_salesforce_data),
    auth_user: str = Depends(verifiy_auth)
):
    print(
        f"Webhook recibido: cambio de correo en cuenta {request.account_id} "
        f"({request.account_name}): {request.old_email} -> {request.new_email}"
    )

    try:
        registrar_cambio_correo(request, sf)
        return AccountEmailChangedResponse(mensaje="Cambio de correo registrado")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error al registrar cambio de correo: {e}")
        raise HTTPException(status_code=500, detail=f"Error del servidor: {str(e)}")
