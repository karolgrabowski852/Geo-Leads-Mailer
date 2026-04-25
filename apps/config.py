import logging
from pydantic_settings import BaseSettings, SettingsConfigDict


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)    

class Config(BaseSettings):
    app_name: str = "GeoLeads Mailer"

    google_location_api_key: str 

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str
    postgres_port: str

    credentials_file: str = "settings/credentials.json"
    token_file: str = "settings/token.json"
    email_attachments_dir: str = "uploads/email_attachments"

    rabbitmq_broker_url: str
    redis_broker_url: str

    django_secret_key: str
    django_settings_module: str
    debug: bool
    allowed_hosts: str
    # csrf_trusted_origins: str


    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",  
    )

config = Config()
