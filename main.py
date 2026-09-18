from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.api.endpoints import folios, cotizacion, registro_campaign, asesores_externos, webhooks
from fastapi.middleware.cors import CORSMiddleware

origins = [
    "*"           
]



import pandas as pd

pd.set_option('future.no_silent_downcasting', True)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Loguea el body crudo y los errores exactos de validación (422) para poder
    diagnosticar peticiones mal formadas (ej. desde Apex) sin tener que redesplegar
    a ciegas. El cuerpo de la respuesta también incluye ambos datos para inspección
    directa (ej. desde Postman o el debug log de Salesforce).
    """
    body_recibido = exc.body
    if isinstance(body_recibido, bytes):
        body_recibido = body_recibido.decode("utf-8", errors="replace")

    print(f"422 Validation Error en {request.method} {request.url.path}")
    print(f"Body recibido: {body_recibido!r}")
    print(f"Errores de validación: {exc.errors()}")

    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body_recibido": body_recibido},
    )


app.include_router(folios.router)
app.include_router(cotizacion.router)
app.include_router(registro_campaign.router)
app.include_router(asesores_externos.router)
app.include_router(webhooks.router)
