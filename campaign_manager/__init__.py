"""Campaign Manager Flask application factory."""
import logging
import os
import sys
from pathlib import Path

from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_compress import Compress

from campaign_manager.config import Config
from campaign_manager import db


def _configure_app_logging():
    """Route app logs to stdout so Railway picks them up.

    Without this, log.info() calls hit the default lastResort handler
    (stderr, WARNING+) and INFO-level messages from the cron job and
    blueprints are silently dropped — leaving no breadcrumbs when a
    scrape hangs.
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    root = logging.getLogger()
    root.setLevel(level)
    has_stdout_stream = any(
        isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout
        for h in root.handlers
    )
    if not has_stdout_stream:
        root.addHandler(handler)

# Frontend build directory (built by Vite into frontend/dist)
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_SCHEDULER_LOCK_PATH = "/tmp/.scheduler.lock"


def _maybe_start_scheduler(app):
    """Start the single process-owned scheduler once database readiness returns.

    Health checks call this after schema repair, allowing a worker that booted
    during a transient migration failure to recover without a process restart.
    The file lock remains the cross-worker ownership boundary.
    """
    if (not app.config.get("SCHEDULER_ENABLED") or not db.is_active()
            or not db.completion_status_repair_ok()
            or getattr(app, "_scheduler_lock", None) is not None):
        return False

    import fcntl
    logger = logging.getLogger("campaign_manager.scheduler_init")
    lock_file = None
    try:
        lock_file = open(_SCHEDULER_LOCK_PATH, "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        from campaign_manager.services.scheduler import init_scheduler
        init_scheduler(
            database_url=app.config["DATABASE_URL"],
            hour=app.config.get("CRON_HOUR", 6),
            minute=app.config.get("CRON_MINUTE", 0),
            campaign_refresh_enabled=app.config.get("CAMPAIGN_REFRESH_SCHEDULER_ENABLED", True),
        )
        # Keep the descriptor open for the process lifetime to retain the lock.
        app._scheduler_lock = lock_file
        logger.info("Scheduler initialized successfully")
        return True
    except (IOError, OSError) as exc:
        logger.info("Scheduler lock not acquired (another worker has it): %s", exc)
    except Exception as exc:
        logger.error("Scheduler init failed: %s", exc, exc_info=True)
    if lock_file is not None:
        lock_file.close()
    return False


def _materialize_tiktok_cookies():
    """Write TIKTOK_COOKIES_TEXT env var to a real file at boot.

    Operator pastes the contents of a Netscape-format cookies.txt
    (exported from a logged-in TikTok browser session) into the
    TIKTOK_COOKIES_TEXT env var on Railway. We write it to /tmp at
    boot and set TIKTOK_COOKIES_FILE so yt-dlp picks it up. This is
    much simpler than mounting a Railway volume just to upload a
    13-line text file.
    """
    text = os.environ.get("TIKTOK_COOKIES_TEXT", "")
    if not text or not text.strip():
        return
    target = "/tmp/tiktok_cookies.txt"
    try:
        with open(target, "w") as f:
            f.write(text)
        os.environ["TIKTOK_COOKIES_FILE"] = target
    except Exception:
        # If /tmp isn't writable (shouldn't happen on Railway), silently
        # skip — the scraper will still run, just without cookies.
        pass


def create_app(config=None):
    # Configure root logging BEFORE anything else — without this, every
    # log.info from blueprints, scheduler, and services is swallowed by
    # the default lastResort handler. Idempotent across workers.
    _configure_app_logging()

    # Materialize cookies BEFORE anything else uses TIKTOK_COOKIES_FILE.
    _materialize_tiktok_cookies()

    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    if config:
        app.config.update(config)

    # Initialize CORS
    CORS(app, origins=app.config["CORS_ORIGINS"])

    # Initialize gzip/brotli response compression. The bundled SPA assets
    # (>700 KB of JS, ~70 KB CSS) and the campaigns list (~80 KB JSON) all
    # have terrible compression-ratio-to-cost without this — turning it on
    # cuts the user-facing payload roughly 4× across the board with
    # negligible CPU cost.
    Compress(app)

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
    from campaign_manager.blueprints.trackers import trackers_bp
    from campaign_manager.blueprints.sound_assignments import sound_assignments_bp
    from campaign_manager.blueprints.scrape_tasks import scrape_tasks_bp
    from campaign_manager.blueprints.efficiency import efficiency_bp
    from campaign_manager.blueprints.creator_intelligence import creator_intelligence_bp
    from campaign_manager.blueprints.creator_library import creator_library_bp
    from campaign_manager.blueprints.chartmetric import chartmetric_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(internal_bp)
    app.register_blueprint(inbox_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(migrate_bp)
    app.register_blueprint(slack_events_bp)
    app.register_blueprint(cron_bp)
    app.register_blueprint(outreach_bp)
    app.register_blueprint(trackers_bp)
    app.register_blueprint(sound_assignments_bp)
    app.register_blueprint(scrape_tasks_bp)
    app.register_blueprint(efficiency_bp)
    app.register_blueprint(creator_intelligence_bp)
    app.register_blueprint(creator_library_bp)
    app.register_blueprint(chartmetric_bp)

    # Initialize Slack bot (no-op if credentials aren't set)
    if app.config.get("SLACK_BOT_TOKEN"):
        from campaign_manager.services.slack_bot import init_slack_app
        try:
            init_slack_app()
        except Exception as e:
            logging.getLogger(__name__).error(
                "Slack bot initialization failed (app will continue without Slack): %s", e
            )

    # Start the scheduler only after required schema repair succeeds. Health
    # checks retry this helper after a transient startup repair failure.
    import logging as _logging
    _sched_log = _logging.getLogger("campaign_manager.scheduler_init")
    schema_ready = db.completion_status_repair_ok()
    _sched_log.info(
        "Scheduler check: SCHEDULER_ENABLED=%s, db_active=%s, schema_repair_ok=%s",
        app.config.get("SCHEDULER_ENABLED"), db.is_active(), schema_ready,
    )
    if app.config.get("SCHEDULER_ENABLED") and db.is_active() and schema_ready:
        _maybe_start_scheduler(app)

    # --- Serve frontend SPA from frontend/dist ---
    if FRONTEND_DIST.is_dir():
        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def serve_frontend(path):
            # Serve static asset if it exists
            full = FRONTEND_DIST / path
            if path and full.is_file():
                return send_from_directory(FRONTEND_DIST, path)
            # SPA fallback: serve index.html for all other routes
            return send_from_directory(FRONTEND_DIST, "index.html")

    return app
