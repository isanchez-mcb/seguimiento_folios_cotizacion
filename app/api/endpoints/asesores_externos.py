from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import AsesorExternoResponse, CreateLeadCampoRequest, CreateLeadCampoResponse
from app.dependencias.sf_service import get_salesforce_data
from app.services.buscarAsesorExterno import buscar_asesor_externo, verificar_cuenta_usuario
from app.services.crearLeadCampo import crear_lead_campo
from app.dependencias.security import verifiy_auth

router = APIRouter()


@router.get("/asesores-externos/buscar", response_model=AsesorExternoResponse, status_code=200, tags=["Asesores Externos"])
def buscar_asesor_externo_endpoint(
    numero_asesor: str,
    sf=Depends(get_salesforce_data),
    auth_user: str = Depends(verifiy_auth)
):
    print(f"Peticion recibida para buscar asesor externo: {auth_user}")

    if not numero_asesor or not numero_asesor.strip():
        raise HTTPException(
            status_code=400,
            detail="El parámetro 'numero_asesor' es requerido"
        )

    asesor = buscar_asesor_externo(numero_asesor.strip(), sf)

    if asesor is None:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró asesor externo con número: {numero_asesor}"
        )

    # ── Corroborar si el asesor tiene una cuenta de usuario activa en Salesforce ──
    user_id = verificar_cuenta_usuario(numero_asesor.strip(), sf)
    if user_id is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"El asesor con número {numero_asesor} no tiene una cuenta "
                "de usuario activa en Salesforce. Favor de verificar con el administrador."
            )
        )

    print("Asesor externo encontrado")
    return asesor


@router.post("/asesores-externos/lead/crear", response_model=CreateLeadCampoResponse, status_code=200, tags=["Asesores Externos"])
def crear_lead_campo_endpoint(
    request: CreateLeadCampoRequest,
    sf=Depends(get_salesforce_data),
    auth_user: str = Depends(verifiy_auth)
):
    print(f"Peticion recibida para crear lead de campo: {auth_user}")

    try:
        lead_id, nombre_completo, nombre_asesor, asesor_telefono, asesor_correo = crear_lead_campo(request, sf)

        print(f"Lead de campo creado exitosamente: {lead_id}")
        return CreateLeadCampoResponse(
            lead_id=lead_id,
            nombre_completo=nombre_completo,
            asesor_asignado=nombre_asesor,
            asesor_telefono=asesor_telefono,
            asesor_correo=asesor_correo
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error al crear lead de campo: {e}")
        raise HTTPException(status_code=500, detail=f"Error del servidor: {str(e)}")
