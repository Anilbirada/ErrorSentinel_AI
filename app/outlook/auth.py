from azure.identity.aio import ClientSecretCredential
from app.config import Settings
def credential(settings: Settings) -> ClientSecretCredential:
    if not settings.graph_ready: raise RuntimeError("Microsoft Graph configuration is incomplete")
    return ClientSecretCredential(settings.ms_tenant_id, settings.ms_client_id, settings.ms_client_secret)
