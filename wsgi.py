"""
PythonAnywhere WSGI configuration.
In the PythonAnywhere web tab, set the WSGI file to point here and set
the working directory to the project root.
"""
import sys
import os

# Add the project directory to the Python path
project_home = os.path.dirname(os.path.abspath(__file__))
if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ["FLASK_ENV"] = "production"

from app import app as application  # noqa: F401, E402
