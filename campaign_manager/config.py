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

    # Slack integration
    SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
    SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
    SLACK_BOOKING_CHANNEL = os.environ.get("SLACK_BOOKING_CHANNEL", "")

    # Anthropic Claude API (for Slack message parsing)
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

    # Apify (TikTok scraping via clockworks/tiktok-scraper)
    APIFY_API_TOKEN = os.environ.get("APIFY_API_TOKEN", "")

    # Scheduler (daily cron)
    SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "false").lower() == "true"
    SLACK_CRON_CHANNEL = os.environ.get("SLACK_CRON_CHANNEL", "")
    SLACK_SOUNDS_CHANNEL = os.environ.get("SLACK_SOUNDS_CHANNEL", "")
    CRON_HOUR = int(os.environ.get("CRON_HOUR", "6"))
    CRON_MINUTE = int(os.environ.get("CRON_MINUTE", "0"))

    # TidesTracker integration
    TIDESTRACKER_API_URL = os.environ.get("TIDESTRACKER_API_URL", "")
    TIDESTRACKER_SERVICE_KEY = os.environ.get("TIDESTRACKER_SERVICE_KEY", "")
    TIDESTRACKER_BASE_URL = os.environ.get("TIDESTRACKER_BASE_URL", "")
