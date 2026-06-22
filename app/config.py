from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    BASIC_AUTH_USERNAME: str
    BASIC_AUTH_PASSWORD: str

    CONSUMER_KEY: str
    CONSUMER_SECRET: str
    url: str

    CONSUMER_KEY_SANDBOX: str
    CONSUMER_SECRET_SANDBOX: str
    url_SANDBOX: str
    APP_ENV: str

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""


settings = Settings()
