from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from typing import Annotated
from app.config import settings

security = HTTPBasic()

def verifiy_auth(credentials: Annotated[HTTPBasicCredentials, Depends(security)]):
    correct_username = credentials.username == settings.BASIC_AUTH_USERNAME
    correct_password = credentials.password == settings.BASIC_AUTH_PASSWORD
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username