"""Application configuration from environment variables."""
import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "campaign-dashboard-local")
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
    NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
    NOTION_CRM_DATABASE_ID = os.environ.get(
        "NOTION_CRM_DATABASE_ID", "1961465b-b829-80c9-a1b5-c4cb3284149a"
    )
    IS_RAILWAY = os.environ.get("RAILWAY_ENVIRONMENT") is not None
