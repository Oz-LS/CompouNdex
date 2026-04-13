import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration shared across all environments."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-before-production")

    # Database — defaults to SQLite; override SQLALCHEMY_DATABASE_URI in env
    # for PostgreSQL migration (e.g. "postgresql://user:pass@host/dbname")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(BASE_DIR, 'reagentario.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # External API keys
    CHEMSPIDER_API_KEY = os.environ.get("CHEMSPIDER_API_KEY", "")

    # File storage
    SDS_UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "sds")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload

    # Server-side sessions (removes ~4 KB cookie limit for label cart)
    SESSION_TYPE = "filesystem"
    SESSION_FILE_DIR = os.path.join(BASE_DIR, "flask_session")
    SESSION_PERMANENT = False
    SESSION_COOKIE_SAMESITE = "Lax"


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = False  # Set True to log SQL queries during dev


class ProductionConfig(Config):
    DEBUG = False


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
