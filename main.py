from fastapi import FastAPI
from app.api.endpoints import folios, cotizacion, asesores_externos
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

app.include_router(folios.router)
app.include_router(cotizacion.router)
app.include_router(asesores_externos.router)
