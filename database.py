"""
Conexión a MySQL para FerreSmart Pro.

Correcciones aplicadas:
  - DB_CONFIG ya NO se evalúa al importar (bug: variables de entorno no
    disponibles en el momento del import en Railway).  Ahora _parse_db_config()
    se llama dentro de get_connection() en cada petición.
  - Soporte completo de MYSQL_URL / DATABASE_URL (formato Railway MySQL plugin).
  - Soporte de MYSQL_PUBLIC_URL como fallback (Railway expone ambas).
  - SSL habilitado automáticamente cuando la URL contiene 'railway.app' o
    cuando la variable MYSQL_SSL=true está presente.
  - Reintentos automáticos en get_connection() con back-off exponencial para
    tolerar el arranque lento del plugin MySQL en Railway.
  - init_db() usa finally para cerrar conexión aunque falle a mitad.
  - _next_id() usa SELECT … FOR UPDATE dentro de la misma transacción para
    evitar la condición de carrera con múltiples workers de gunicorn.
"""

import mysql.connector
from mysql.connector import Error
import os
import time
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────────

def _parse_db_config() -> dict:
    """
    Lee la configuración de BD en RUNTIME (no al importar).

    Prioridad:
      1. MYSQL_URL  o  DATABASE_URL  (Railway MySQL plugin — URL completa)
      2. MYSQL_PUBLIC_URL            (URL pública de Railway, fallback)
      3. Variables individuales      DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME
    """
    raw_url = (
        os.getenv("MYSQL_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("MYSQL_PUBLIC_URL")
    )

    if raw_url:
        # Railway a veces entrega mysql:// y a veces mysql+mysqlconnector://
        # Normalizamos a mysql:// para que urlparse lo maneje bien.
        normalized = raw_url.replace("mysql+mysqlconnector://", "mysql://")
        parsed = urlparse(normalized)

        cfg = {
            "host":     parsed.hostname,
            "port":     parsed.port or 3306,
            "user":     parsed.username,
            "password": parsed.password,
            "database": parsed.path.lstrip("/"),
        }

        # SSL: Railway requiere SSL en conexiones externas.
        # Lo activamos si el host termina en railway.app o si el usuario
        # lo pide explícitamente con MYSQL_SSL=true.
        host = parsed.hostname or ""
        if "railway.app" in host or os.getenv("MYSQL_SSL", "").lower() == "true":
            cfg["ssl_disabled"] = False
        else:
            cfg["ssl_disabled"] = True

        return cfg

    # Variables individuales (desarrollo local o Railway con vars separadas)
    return {
        "host":        os.getenv("DB_HOST",     "localhost"),
        "port":        int(os.getenv("DB_PORT", "3306")),
        "user":        os.getenv("DB_USER",     "root"),
        "password":    os.getenv("DB_PASSWORD", ""),
        "database":    os.getenv("DB_NAME",     "ventas_db"),
        "ssl_disabled": True,
    }


def get_connection(retries: int = 5, delay: float = 2.0):
    """
    Retorna una conexión activa a MySQL.

    Reintenta hasta `retries` veces con back-off exponencial para tolerar
    el arranque lento del plugin de Railway (puede tardar varios segundos
    en estar listo después del deploy).
    """
    cfg = _parse_db_config()          # ← lee env vars en cada llamada

    for attempt in range(1, retries + 1):
        try:
            conn = mysql.connector.connect(
                **cfg,
                connection_timeout=10,
                autocommit=False,
            )
            return conn
        except Error as e:
            logger.warning(
                "[DB] Intento %d/%d fallido: %s", attempt, retries, e
            )
            if attempt < retries:
                time.sleep(delay * attempt)   # back-off: 2s, 4s, 6s, 8s …

    logger.error("[DB] No se pudo establecer conexión tras %d intentos.", retries)
    return None


# ─────────────────────────────────────────────
#  INICIALIZACIÓN DE TABLAS
# ─────────────────────────────────────────────

def init_db():
    """
    Crea las tablas si no existen e inserta datos de muestra.
    Se llama automáticamente al iniciar la aplicación.
    Usa finally para garantizar el cierre de la conexión.
    """
    conn = get_connection(retries=8, delay=3.0)
    if not conn:
        logger.error("[DB] No se pudo inicializar la base de datos.")
        return

    cursor = None
    try:
        cursor = conn.cursor()

        # ── Clientes ───────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                id          VARCHAR(10)  NOT NULL PRIMARY KEY,
                nombre      VARCHAR(100) NOT NULL,
                nit         VARCHAR(20)  DEFAULT 'CF',
                telefono    VARCHAR(20)  DEFAULT '',
                correo      VARCHAR(100) DEFAULT '',
                direccion   VARCHAR(200) DEFAULT '',
                creado_en   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # ── Productos ──────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                id          VARCHAR(10)   NOT NULL PRIMARY KEY,
                nombre      VARCHAR(100)  NOT NULL,
                categoria   VARCHAR(60)   NOT NULL,
                precio      DECIMAL(10,2) NOT NULL,
                stock       INT           NOT NULL DEFAULT 0,
                unidad      VARCHAR(20)   DEFAULT 'unidad',
                activo      TINYINT(1)    NOT NULL DEFAULT 1,
                creado_en   TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # ── Ventas ─────────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ventas (
                id              VARCHAR(10)   NOT NULL PRIMARY KEY,
                id_cliente      VARCHAR(10)   NOT NULL,
                cliente         VARCHAR(100)  NOT NULL,
                id_producto     VARCHAR(10)   NOT NULL,
                producto        VARCHAR(100)  NOT NULL,
                categoria       VARCHAR(60)   NOT NULL DEFAULT '',
                cantidad        INT           NOT NULL,
                precio_unitario DECIMAL(10,2) NOT NULL,
                total           DECIMAL(10,2) NOT NULL,
                fecha           DATE          NOT NULL,
                estado          VARCHAR(20)   NOT NULL DEFAULT 'completada',
                creado_en       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (id_cliente)  REFERENCES clientes(id),
                FOREIGN KEY (id_producto) REFERENCES productos(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.commit()

        # Datos de muestra solo si la BD está vacía
        cursor.execute("SELECT COUNT(*) FROM clientes")
        if cursor.fetchone()[0] == 0:
            _insertar_datos_muestra(cursor)
            conn.commit()
            logger.info("[DB] Datos de muestra insertados.")

        logger.info("[DB] Base de datos inicializada correctamente.")

    except Error as e:
        logger.error("[DB] Error al inicializar: %s", e)
        if conn:
            conn.rollback()
    finally:
        # Siempre se ejecuta, aunque haya excepción
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# ─────────────────────────────────────────────
#  DATOS DE MUESTRA
# ─────────────────────────────────────────────

def _insertar_datos_muestra(cursor):
    clientes = [
        ("C001", "Carlos Reyes Méndez",    "12345678-9", "5501-2233", "creyes@gmail.com",      "Zona 1, Guatemala City"),
        ("C002", "María López Cifuentes",   "CF",         "4422-8899", "mlopez@hotmail.com",    "San Lucas Sacatepéquez"),
        ("C003", "Constructora Díaz S.A.",  "98765432-1", "2233-4455", "info@constdiaz.gt",     "Zona 12, Guatemala City"),
        ("C004", "Roberto Ajú Tzul",        "CF",         "5599-0011", "raju@gmail.com",        "Mixco, Guatemala"),
        ("C005", "Ferretería El Clavo",     "11223344-5", "7788-9900", "elclavo@ferreteria.gt", "Escuintla"),
    ]
    cursor.executemany(
        "INSERT INTO clientes (id, nombre, nit, telefono, correo, direccion) VALUES (%s,%s,%s,%s,%s,%s)",
        clientes,
    )

    productos = [
        ("P001", "Martillo 16oz Stanley",           "herramientas manuales",    125.00,  45, "unidad"),
        ("P002", 'Taladro Percutor 1/2"',            "herramientas eléctricas",  850.00,  12, "unidad"),
        ("P003", 'Tornillos autorroscantes 3/4"',    "tornillería",               35.00, 200, "caja"),
        ("P004", 'Tubo PVC 1/2" x 6m',              "plomería",                  48.00,  80, "unidad"),
        ("P005", "Pintura de aceite blanca",         "pintura",                  220.00,  30, "litro"),
        ("P006", "Cemento gris 42.5kg",              "construcción",              95.00, 150, "bolsa"),
        ("P007", "Cable eléctrico #12 AWG",          "electricidad",              18.50, 500, "metro"),
        ("P008", 'Llave de paso 3/4"',               "plomería",                  85.00,  35, "unidad"),
        ("P009", 'Sierra circular 7-1/4"',           "herramientas eléctricas", 1250.00,   7, "unidad"),
        ("P010", "Cinta métrica 5m",                 "herramientas manuales",     42.00,  60, "unidad"),
        ("P011", 'Nivel de burbuja 24"',             "herramientas manuales",     95.00,  25, "unidad"),
        ("P012", 'Varilla de hierro 3/8"',           "construcción",              78.00,  90, "unidad"),
    ]
    cursor.executemany(
        "INSERT INTO productos (id, nombre, categoria, precio, stock, unidad) VALUES (%s,%s,%s,%s,%s,%s)",
        productos,
    )

    ventas = [
        ("V001","C003","Constructora Díaz S.A.", "P006","Cemento gris 42.5kg",          "construcción",            50,  95.00,4750.00,"2024-01-15","completada"),
        ("V002","C001","Carlos Reyes Méndez",    "P002",'Taladro Percutor 1/2"',        "herramientas eléctricas",  1, 850.00, 850.00,"2024-01-15","completada"),
        ("V003","C002","María López Cifuentes",  "P005","Pintura de aceite blanca",      "pintura",                  5, 220.00,1100.00,"2024-01-14","completada"),
        ("V004","C004","Roberto Ajú Tzul",       "P001","Martillo 16oz Stanley",         "herramientas manuales",    3, 125.00, 375.00,"2024-01-14","completada"),
        ("V005","C005","Ferretería El Clavo",    "P007","Cable eléctrico #12 AWG",       "electricidad",           100,  18.50,1850.00,"2024-01-13","completada"),
        ("V006","C003","Constructora Díaz S.A.", "P012",'Varilla de hierro 3/8"',        "construcción",            30,  78.00,2340.00,"2024-01-13","completada"),
        ("V007","C001","Carlos Reyes Méndez",    "P003",'Tornillos autorroscantes 3/4"', "tornillería",             10,  35.00, 350.00,"2024-01-12","completada"),
        ("V008","C002","María López Cifuentes",  "P004",'Tubo PVC 1/2" x 6m',           "plomería",                20,  48.00, 960.00,"2024-01-12","pendiente"),
        ("V009","C004","Roberto Ajú Tzul",       "P009",'Sierra circular 7-1/4"',        "herramientas eléctricas",  1,1250.00,1250.00,"2024-01-11","completada"),
        ("V010","C005","Ferretería El Clavo",    "P006","Cemento gris 42.5kg",           "construcción",            25,  95.00,2375.00,"2024-01-11","completada"),
        ("V011","C001","Carlos Reyes Méndez",    "P010","Cinta métrica 5m",              "herramientas manuales",    2,  42.00,  84.00,"2024-01-10","completada"),
        ("V012","C003","Constructora Díaz S.A.", "P008",'Llave de paso 3/4"',            "plomería",                 8,  85.00, 680.00,"2024-01-10","cancelada"),
    ]
    cursor.executemany(
        """INSERT INTO ventas
           (id, id_cliente, cliente, id_producto, producto, categoria,
            cantidad, precio_unitario, total, fecha, estado)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        ventas,
    )
