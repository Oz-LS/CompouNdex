import os
from flask import Flask, render_template
from flask_session import Session
from config import config_map
from extensions import db, migrate


def create_app(env: str = None) -> Flask:
    """Application factory. ``env`` selects the Config class to use."""
    env = env or os.environ.get("FLASK_ENV", "default")
    app = Flask(__name__)
    app.config.from_object(config_map[env])

    # Ensure required directories exist
    os.makedirs(app.config["SDS_UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(os.path.join(app.static_folder, "guidelines"), exist_ok=True)
    os.makedirs(os.path.join(app.static_folder, "pictograms"), exist_ok=True)

    # Initialise extensions
    db.init_app(app)
    migrate.init_app(app, db)
    Session(app)

    # Import models so Flask-Migrate / db.create_all() can detect them
    with app.app_context():
        from models import reagent, inventory_item, sds_document, mixture  # noqa: F401
        # Create tables if they don't exist yet (safe to call on every startup)
        db.create_all()

    # ── Blueprints ─────────────────────────────────────────────────────────
    from blueprints.search import search_bp
    from blueprints.inventory import inventory_bp
    from blueprints.labels import labels_bp
    from blueprints.guidelines import guidelines_bp
    from blueprints.reagent import reagent_bp
    from blueprints.mixtures import mixtures_bp

    app.register_blueprint(search_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(labels_bp)
    app.register_blueprint(guidelines_bp)
    app.register_blueprint(reagent_bp)
    app.register_blueprint(mixtures_bp)

    # ── Homepage ───────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return render_template("home.html")

    # ── Error handlers ─────────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    @app.errorhandler(413)
    def too_large(e):
        return render_template(
            "errors/generic.html",
            code=413,
            title="File Too Large",
            message="The uploaded file exceeds the 16 MB limit.",
        ), 413

    return app


# Module-level app instance for PythonAnywhere WSGI and `flask` CLI
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
