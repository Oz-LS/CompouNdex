from flask import Blueprint

inventory_bp = Blueprint("inventory", __name__, url_prefix="/inventory")

from . import routes  # noqa: F401, E402
