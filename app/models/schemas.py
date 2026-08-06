from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
from datetime import date, datetime
from typing import Dict, Any

app = FastAPI()

class FolioRequest(BaseModel):
    CaseNumber : str

class FolioResponse(BaseModel):
    Case_List: Dict[str, Any]

class AutoData(BaseModel):
    cp: str
    modelo: str
    marca: str
    version: str
    fecha_nacimiento_conductor: date
    genero: str

class GMMData(BaseModel):
    negocio: str
    genero: str
    edad: int

class HogarData(BaseModel):
    tipo_de_vivienda: str
    propietario: bool
    cp: str

class VidaTotalData(BaseModel):
    genero: str
    edad: int
    fumador: bool

class VidaMasData(BaseModel):
    fecha_nacimiento: date
    genero: str
    fumador: bool

class PlanSeguroData(BaseModel):
    genero: str
    fecha_nacimiento: date
    estado: str

class MascotaData(BaseModel):
    raza: str
    edad_mascota: int
    tipo_mascota: str
    genero_mascota: str
    cp_contrante: str
    edad_contratante: int

class ViajesData(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    pais_region: str
    no_asegurados: int
    mayores_de_edad: bool

class CreateCotizacionRequest(BaseModel):
    nombre: str
    expediente_colaborador: Optional[str] = None
    telefono: str
    auto_data: Optional[AutoData] = None
    gmm_data: Optional[GMMData] = None
    hogar_data: Optional[HogarData] = None
    vida_total_data: Optional[VidaTotalData] = None
    vida_mas_data: Optional[VidaMasData] = None
    plan_seguro_data: Optional[PlanSeguroData] = None
    mascota_data: Optional[MascotaData] = None
    viajes_data: Optional[ViajesData] = None

class RegistroCampaignRequest(BaseModel):
    expediente: Optional[str] = None
    telefono: Optional[str] = None
    correo: Optional[str] = None
    negocio: Optional[str] = None
    primer_nombre: Optional[str] = None
    segundo_nombre: Optional[str] = None
    apellidos: Optional[str] = None
    ocupacion: Optional[str] = None
    numero_asesor: Optional[str] = None

class RegistroCampaignResponse(BaseModel):
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    lead_id: Optional[str] = None
    campaign_member_id: str
    negocio: str

class CreateCotizacionResponse(BaseModel):
    asesor: str
