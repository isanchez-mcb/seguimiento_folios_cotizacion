"""
Endpoint de Trazabilidad End-to-End de Asesores (Agente Lucía).

Solo consulta (GET). No crea ni modifica registros en Salesforce.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencias.security import verifiy_auth
from app.dependencias.sf_service import get_salesforce_data
from app.models.schemas import SeguimientoAsesorResponse
from app.services.trazabilidad_asesor import (
    STATUS_LEAD_VALIDOS,
    STAGE_OPP_VALIDOS,
    RAMOS_VALIDOS,
    obtener_trazabilidad_asesor,
)

router = APIRouter()


@router.get(
    "/api/v1/seguimiento/asesor",
    response_model=SeguimientoAsesorResponse,
    status_code=200,
    tags=["Seguimiento Asesor"],
)
def obtener_seguimiento_asesor(
    numero_asesor: str = Query(..., description="Número del Asesor Externo (obligatorio)"),
    status_lead: Optional[str] = Query(
        None,
        description="Filtra por Status exacto del Lead. Válidos: Nuevo, Stand by, Convertido, No convertido",
    ),
    stage_opp: Optional[str] = Query(
        None,
        description="Filtra por StageName de la Oportunidad. Válidos: Nueva, Cotización, Proceso de cierre, Cerrado ganado, Póliza emitida, Póliza no emitida, Concluido, Otros (etapas inactivas/rezagadas)",
    ),
    ramo: Optional[str] = Query(
        None,
        description="Filtra por Ramo/Ramos_de_interes (Lead, Oportunidad o Folio). Válidos: VIDA, DAÑOS, ACCIDENTES Y ENFERMEDADES",
    ),
    fecha_inicio: Optional[str] = Query(
        None,
        description="Filtra registros creados a partir de esta fecha (YYYY-MM-DD)",
    ),
    fecha_fin: Optional[str] = Query(
        None,
        description="Filtra registros creados hasta esta fecha (YYYY-MM-DD)",
    ),
    periodo: Optional[str] = Query(
        None,
        description="Filtra por periodo (YYYY-MM o YYYY-MM:YYYY-MM). Aplica si el Lead, la Oportunidad o alguna Póliza cae en el periodo",
    ),
    con_folio: Optional[bool] = Query(
        None,
        description="Si true, solo items con folios de emisión. Si false, solo items sin folios de emisión",
    ),
    page: int = Query(0, ge=0, description="Índice de página (zero-based)"),
    size: int = Query(10, ge=1, le=100, description="Cantidad de registros por página"),
    sf=Depends(get_salesforce_data),
    auth_user: str = Depends(verifiy_auth),
):
    """
    Consulta la trazabilidad end-to-end de un asesor externo.

    Retorna una matriz aplanada de seguimiento con KPIs agregados y paginación.
    """
    print(f"Peticion recibida para trazabilidad de asesor: {auth_user}")

    # ── Validar numero_asesor (TC-05) ────────────────────────────
    if not numero_asesor or not numero_asesor.strip():
        raise HTTPException(
            status_code=400,
            detail="El parámetro 'numero_asesor' es requerido.",
        )

    numero_asesor = numero_asesor.strip()

    # ── Validar status_lead ──────────────────────────────────────
    if status_lead and status_lead not in STATUS_LEAD_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Valor inválido para 'status_lead': '{status_lead}'. "
                f"Válidos: {', '.join(sorted(STATUS_LEAD_VALIDOS))}"
            ),
        )

    # ── Validar stage_opp ────────────────────────────────────────
    if stage_opp and stage_opp not in STAGE_OPP_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Valor inválido para 'stage_opp': '{stage_opp}'. "
                f"Válidos: {', '.join(sorted(STAGE_OPP_VALIDOS))}"
            ),
        )

    # ── Validar ramo ──────────────────────────────────────────────
    if ramo and ramo not in RAMOS_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Valor inválido para 'ramo': '{ramo}'. "
                f"Válidos: {', '.join(sorted(RAMOS_VALIDOS))}"
            ),
        )

    try:
        resultado = obtener_trazabilidad_asesor(
            sf=sf,
            numero_asesor=numero_asesor,
            status_lead=status_lead,
            stage_opp=stage_opp,
            ramo=ramo,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            periodo=periodo,
            con_folio=con_folio,
            page=page,
            size=size,
        )
        return resultado
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error en trazabilidad de asesor: {e}")
        raise HTTPException(status_code=500, detail=f"Error del servidor: {str(e)}")