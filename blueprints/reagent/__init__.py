from flask import Blueprint

reagent_bp = Blueprint("reagent", __name__, url_prefix="/reagent")

from . import routes  # noqa: F401, E402
