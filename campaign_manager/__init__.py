"""Campaign Manager Flask application factory."""
from flask import Flask
from flask_cors import CORS

from campaign_manager.config import Config
from campaign_manager import db


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)

    # Initialize CORS
    CORS(app, origins=app.config["CORS_ORIGINS"])

    # Initialize database
    db.init(app.config.get("DATABASE_URL"))

    from campaign_manager.blueprints.health import health_bp
    from campaign_manager.blueprints.campaigns import campaigns_bp
    from campaign_manager.blueprints.internal import internal_bp
    from campaign_manager.blueprints.inbox import inbox_bp
    from campaign_manager.blueprints.webhooks import webhooks_bp
    from campaign_manager.blueprints.migrate import migrate_bp
    from campaign_manager.blueprints.slack_events import slack_events_bp
    from campaign_manager.blueprints.cron import cron_bp
    from campaign_manager.blueprints.outreach import outreach_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(internal_bp)
    app.register_blueprint(inbox_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(migrate_bp)
    app.register_blueprint(slack_events_bp)
    app.register_blueprint(cron_bp)
    app.register_blueprint(outreach_bp)

    # Initialize Slack bot (no-op if credentials aren't set)
    if app.config.get("SLACK_BOT_TOKEN"):
        from campaign_manager.services.slack_bot import init_slack_app
        init_slack_app()

    # Initialize scheduler (only if enabled and DB is active).
    # Use a file lock so only one gunicorn worker runs the scheduler.
    import logging as _logging
    _sched_log = _logging.getLogger("campaign_manager.scheduler_init")
    _sched_log.info("Scheduler check: SCHEDULER_ENABLED=%s, db_active=%s",
                    app.config.get("SCHEDULER_ENABLED"), db.is_active())
    if app.config.get("SCHEDULER_ENABLED") and db.is_active():
        import fcntl
        try:
            _lock_file = open("/tmp/.scheduler.lock", "w")
            fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _sched_log.info("Got scheduler lock, initializing...")
            # Got the lock — this worker runs the scheduler
            from campaign_manager.services.scheduler import init_scheduler
            init_scheduler(
                database_url=app.config["DATABASE_URL"],
                hour=app.config.get("CRON_HOUR", 6),
                minute=app.config.get("CRON_MINUTE", 0),
            )
            # Keep _lock_file open (holds the lock for process lifetime)
            app._scheduler_lock = _lock_file
            _sched_log.info("Scheduler initialized successfully")
        except (IOError, OSError) as e:
            _sched_log.info("Scheduler lock not acquired (another worker has it): %s", e)
        except Exception as e:
            _sched_log.error("Scheduler init failed: %s", e, exc_info=True)

    return app
