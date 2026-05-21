"""
Punto de entrada de FerreSmart Pro.

Correcciones aplicadas:
  - Logging configurado desde el arranque para que los mensajes de
    database.py y routes.py aparezcan en los logs de Railway.
  - SECRET_KEY emite advertencia si sigue siendo el valor por defecto
    en un entorno de producción.
"""

import os
import logging
from flask import Flask, send_from_directory
from flask_cors import CORS

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Aplicación ───────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static", template_folder=".")

secret_key = os.getenv("SECRET_KEY", "ferresmart_dev_secret_change_in_prod")
if secret_key == "ferresmart_dev_secret_change_in_prod":
    logger.warning(
        "SECRET_KEY usa el valor por defecto. "
        "Define la variable de entorno SECRET_KEY en Railway antes de ir a producción."
    )
app.secret_key = secret_key

# CORS solo para rutas /api — el frontend se sirve desde el mismo origen
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ── Inicializar BD ───────────────────────────────────────────────────
from database import init_db
init_db()

# ── Blueprints ───────────────────────────────────────────────────────
from routes import api_bp
app.register_blueprint(api_bp, url_prefix="/api")

# ── Frontend (SPA) ───────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "index.html")

# ── Arranque local ───────────────────────────────────────────────────
if __name__ == "__main__":
    port  = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV", "production") == "development"
    app.run(debug=debug, host="0.0.0.0", port=port)
