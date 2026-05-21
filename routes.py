"""
API REST — FerreSmart Pro
Prefijo: /api

Correcciones aplicadas:
  - Todos los endpoints usan finally para cerrar cursor y conexión,
    incluso si ocurre una excepción (evita agotamiento del pool de MySQL).
  - _next_id() usa SELECT … FOR UPDATE dentro de la misma transacción
    para eliminar la condición de carrera entre workers de gunicorn.
  - GET /api/productos invalida el caché al crear un producto nuevo.
  - crear_cliente() devuelve solo los campos que realmente se guardaron
    en la BD, no un reflejo del body del request.
  - _next_id() valida que la tabla sea una de las permitidas (evita
    interpolación arbitraria en el SQL).
"""

from flask import Blueprint, jsonify, request
from database import get_connection
from structures import pila_ventas, tabla_productos
from datetime import date, datetime
import logging

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__)

# Tablas permitidas en _next_id — previene interpolación arbitraria en SQL
_TABLAS_VALIDAS = {"clientes", "productos", "ventas"}


# ═══════════════════════════════════════════════
#  UTILIDADES
# ═══════════════════════════════════════════════

def _row_to_dict(cursor, row):
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))


def _serialize(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return str(obj)


def _json(data, status=200):
    return jsonify(data), status


def _next_id(cursor, tabla: str, prefijo: str) -> str:
    """
    Genera el siguiente ID correlativo: C006, V013, P013…

    Usa SELECT … FOR UPDATE para evitar la condición de carrera que
    ocurría cuando dos workers de gunicorn ejecutaban el SELECT y el
    INSERT de forma entrelazada, generando PKs duplicadas.

    IMPORTANTE: el llamador debe hacer conn.commit() después del INSERT
    para liberar el bloqueo.
    """
    if tabla not in _TABLAS_VALIDAS:
        raise ValueError(f"Tabla no permitida: {tabla!r}")

    # La query se construye con una tabla validada contra un conjunto
    # de literales — no hay riesgo de inyección.
    cursor.execute(
        f"SELECT MAX(CAST(SUBSTRING(id, 2) AS UNSIGNED)) FROM {tabla} FOR UPDATE"
    )
    result = cursor.fetchone()[0]
    n = (result or 0) + 1
    return f"{prefijo}{str(n).zfill(3)}"


# ═══════════════════════════════════════════════
#  VENTAS
# ═══════════════════════════════════════════════

@api_bp.route("/ventas", methods=["GET"])
def get_ventas():
    """GET /api/ventas — Todas las ventas ordenadas por fecha DESC."""
    conn = get_connection()
    if not conn:
        return _json({"error": "No se pudo conectar a la base de datos"}, 500)

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, id_cliente, cliente, id_producto, producto, categoria,
                   cantidad, precio_unitario, total, fecha, estado
            FROM ventas
            ORDER BY fecha DESC, creado_en DESC
        """)
        rows = cursor.fetchall()
        ventas = []
        for row in rows:
            d = _row_to_dict(cursor, row)
            d["fecha"] = _serialize(d["fecha"])
            d["precio_unitario"] = float(d["precio_unitario"])
            d["total"] = float(d["total"])
            ventas.append(d)

        pila_ventas.cargar_desde_lista(ventas)
        return _json(ventas)

    except Exception as e:
        logger.error("[GET /ventas] %s", e)
        return _json({"error": str(e)}, 500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@api_bp.route("/ventas", methods=["POST"])
def crear_venta():
    """
    POST /api/ventas
    Body JSON: { id_cliente, cliente, id_producto, producto, categoria,
                 cantidad, precio_unitario, total, fecha?, estado? }
    """
    data = request.get_json(silent=True) or {}

    required = ["id_cliente", "cliente", "id_producto", "producto",
                 "cantidad", "precio_unitario", "total"]
    for campo in required:
        if not data.get(campo):
            return _json({"error": f"Campo requerido: {campo}"}, 400)

    conn = get_connection()
    if not conn:
        return _json({"error": "Conexión fallida"}, 500)

    cursor = None
    try:
        cursor = conn.cursor()
        new_id = _next_id(cursor, "ventas", "V")
        hoy = data.get("fecha", str(date.today()))

        cursor.execute("""
            INSERT INTO ventas
            (id, id_cliente, cliente, id_producto, producto, categoria,
             cantidad, precio_unitario, total, fecha, estado)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            new_id,
            data["id_cliente"],
            data["cliente"],
            data["id_producto"],
            data["producto"],
            data.get("categoria", ""),
            int(data["cantidad"]),
            float(data["precio_unitario"]),
            float(data["total"]),
            hoy,
            data.get("estado", "completada"),
        ))
        conn.commit()

        nueva_venta = {
            "id":              new_id,
            "id_cliente":      data["id_cliente"],
            "cliente":         data["cliente"],
            "id_producto":     data["id_producto"],
            "producto":        data["producto"],
            "categoria":       data.get("categoria", ""),
            "cantidad":        int(data["cantidad"]),
            "precio_unitario": float(data["precio_unitario"]),
            "total":           float(data["total"]),
            "fecha":           hoy,
            "estado":          data.get("estado", "completada"),
        }
        pila_ventas.push(nueva_venta)
        return _json(nueva_venta, 201)

    except Exception as e:
        logger.error("[POST /ventas] %s", e)
        if conn:
            conn.rollback()
        return _json({"error": str(e)}, 500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# ═══════════════════════════════════════════════
#  CLIENTES
# ═══════════════════════════════════════════════

@api_bp.route("/clientes", methods=["GET"])
def get_clientes():
    """GET /api/clientes — Todos los clientes."""
    conn = get_connection()
    if not conn:
        return _json({"error": "Conexión fallida"}, 500)

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, nombre, nit, telefono, correo, direccion FROM clientes ORDER BY nombre"
        )
        rows = cursor.fetchall()
        return _json([_row_to_dict(cursor, r) for r in rows])

    except Exception as e:
        logger.error("[GET /clientes] %s", e)
        return _json({"error": str(e)}, 500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@api_bp.route("/clientes", methods=["POST"])
def crear_cliente():
    """POST /api/clientes"""
    data = request.get_json(silent=True) or {}
    if not data.get("nombre"):
        return _json({"error": "Campo requerido: nombre"}, 400)

    conn = get_connection()
    if not conn:
        return _json({"error": "Conexión fallida"}, 500)

    cursor = None
    try:
        cursor = conn.cursor()
        new_id = data.get("id") or _next_id(cursor, "clientes", "C")
        cursor.execute("""
            INSERT INTO clientes (id, nombre, nit, telefono, correo, direccion)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (
            new_id,
            data["nombre"],
            data.get("nit", "CF"),
            data.get("telefono", ""),
            data.get("correo", ""),
            data.get("direccion", ""),
        ))
        conn.commit()

        # Devuelve solo los campos guardados en BD, no un reflejo del request
        nuevo = {
            "id":        new_id,
            "nombre":    data["nombre"],
            "nit":       data.get("nit", "CF"),
            "telefono":  data.get("telefono", ""),
            "correo":    data.get("correo", ""),
            "direccion": data.get("direccion", ""),
        }
        return _json(nuevo, 201)

    except Exception as e:
        logger.error("[POST /clientes] %s", e)
        if conn:
            conn.rollback()
        return _json({"error": str(e)}, 500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# ═══════════════════════════════════════════════
#  PRODUCTOS
# ═══════════════════════════════════════════════

@api_bp.route("/productos", methods=["GET"])
def get_productos():
    """GET /api/productos — Todos los productos activos."""
    if tabla_productos.total() > 0:
        return _json(tabla_productos.todos())

    conn = get_connection()
    if not conn:
        return _json({"error": "Conexión fallida"}, 500)

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, nombre, categoria, precio, stock, unidad
            FROM productos WHERE activo=1 ORDER BY categoria, nombre
        """)
        rows = cursor.fetchall()
        productos = []
        for r in rows:
            d = _row_to_dict(cursor, r)
            d["precio"] = float(d["precio"])
            productos.append(d)
        tabla_productos.cargar_desde_lista(productos)
        return _json(productos)

    except Exception as e:
        logger.error("[GET /productos] %s", e)
        return _json({"error": str(e)}, 500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@api_bp.route("/productos/<string:id>", methods=["GET"])
def get_producto(id):
    """GET /api/productos/<id> — Búsqueda O(1) por tabla hash."""
    producto = tabla_productos.buscar(id)
    if producto:
        return _json(producto)

    conn = get_connection()
    if not conn:
        return _json({"error": "Conexión fallida"}, 500)

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, nombre, categoria, precio, stock, unidad FROM productos WHERE id=%s AND activo=1",
            (id.upper(),)
        )
        row = cursor.fetchone()
        if not row:
            return _json({"error": "Producto no encontrado"}, 404)
        producto = _row_to_dict(cursor, row)
        producto["precio"] = float(producto["precio"])
        tabla_productos.insertar(id, producto)
        return _json(producto)

    except Exception as e:
        logger.error("[GET /productos/%s] %s", id, e)
        return _json({"error": str(e)}, 500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@api_bp.route("/productos", methods=["POST"])
def crear_producto():
    """POST /api/productos"""
    data = request.get_json(silent=True) or {}
    if not data.get("nombre") or not data.get("precio"):
        return _json({"error": "Campos requeridos: nombre, precio"}, 400)

    conn = get_connection()
    if not conn:
        return _json({"error": "Conexión fallida"}, 500)

    cursor = None
    try:
        cursor = conn.cursor()
        new_id = data.get("id") or _next_id(cursor, "productos", "P")
        precio  = float(data["precio"])
        stock   = int(data.get("stock", 0))
        categoria = data.get("categoria", "herramientas manuales")
        unidad    = data.get("unidad", "unidad")

        cursor.execute("""
            INSERT INTO productos (id, nombre, categoria, precio, stock, unidad)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (new_id, data["nombre"], categoria, precio, stock, unidad))
        conn.commit()

        nuevo = {
            "id":        new_id,
            "nombre":    data["nombre"],
            "categoria": categoria,
            "precio":    precio,
            "stock":     stock,
            "unidad":    unidad,
        }
        # Invalidar caché para que el próximo GET /productos consulte MySQL
        tabla_productos.limpiar()
        return _json(nuevo, 201)

    except Exception as e:
        logger.error("[POST /productos] %s", e)
        if conn:
            conn.rollback()
        return _json({"error": str(e)}, 500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# ═══════════════════════════════════════════════
#  ANÁLISIS / DASHBOARD
# ═══════════════════════════════════════════════

@api_bp.route("/analisis/resumen", methods=["GET"])
def resumen():
    """GET /api/analisis/resumen — KPIs para el dashboard."""
    conn = get_connection()
    if not conn:
        return _json({"error": "Conexión fallida"}, 500)

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(total),0) FROM ventas")
        cnt_total, total_ingresos = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM clientes")
        total_clientes = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM productos WHERE activo=1")
        total_productos = cursor.fetchone()[0]
        return _json({
            "total_ventas":    int(cnt_total),
            "total_ingresos":  float(total_ingresos),
            "total_clientes":  int(total_clientes),
            "total_productos": int(total_productos),
            "pila_tamano":     pila_ventas.tamano(),
            "hash_tamano":     tabla_productos.total(),
        })

    except Exception as e:
        logger.error("[GET /analisis/resumen] %s", e)
        return _json({"error": str(e)}, 500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@api_bp.route("/analisis/diario", methods=["GET"])
def ventas_diarias():
    """GET /api/analisis/diario — Ventas agrupadas por día."""
    dias = int(request.args.get("dias", 7))
    conn = get_connection()
    if not conn:
        return _json({"error": "Conexión fallida"}, 500)

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT fecha, COUNT(*) AS transacciones, SUM(total) AS ingresos
            FROM ventas
            WHERE fecha >= CURDATE() - INTERVAL %s DAY
            GROUP BY fecha ORDER BY fecha ASC
        """, (dias,))
        rows = cursor.fetchall()
        data = [
            {"fecha": str(r[0]), "transacciones": int(r[1]), "ingresos": float(r[2])}
            for r in rows
        ]
        return _json(data)

    except Exception as e:
        logger.error("[GET /analisis/diario] %s", e)
        return _json({"error": str(e)}, 500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@api_bp.route("/analisis/top-productos", methods=["GET"])
def top_productos():
    """GET /api/analisis/top-productos"""
    limite = int(request.args.get("limite", 8))
    conn = get_connection()
    if not conn:
        return _json({"error": "Conexión fallida"}, 500)

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT producto, categoria,
                   SUM(cantidad) AS unidades, SUM(total) AS ingresos, COUNT(*) AS tx
            FROM ventas
            GROUP BY producto, categoria
            ORDER BY ingresos DESC
            LIMIT %s
        """, (limite,))
        rows = cursor.fetchall()
        data = [
            {"producto": r[0], "categoria": r[1],
             "unidades": int(r[2]), "ingresos": float(r[3]), "transacciones": int(r[4])}
            for r in rows
        ]
        return _json(data)

    except Exception as e:
        logger.error("[GET /analisis/top-productos] %s", e)
        return _json({"error": str(e)}, 500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@api_bp.route("/analisis/por-categoria", methods=["GET"])
def por_categoria():
    """GET /api/analisis/por-categoria"""
    conn = get_connection()
    if not conn:
        return _json({"error": "Conexión fallida"}, 500)

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT categoria, SUM(total) AS ingresos, COUNT(*) AS transacciones
            FROM ventas GROUP BY categoria ORDER BY ingresos DESC
        """)
        rows = cursor.fetchall()
        data = [
            {"categoria": r[0], "ingresos": float(r[1]), "transacciones": int(r[2])}
            for r in rows
        ]
        return _json(data)

    except Exception as e:
        logger.error("[GET /analisis/por-categoria] %s", e)
        return _json({"error": str(e)}, 500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# ═══════════════════════════════════════════════
#  ESTRUCTURAS — diagnóstico
# ═══════════════════════════════════════════════

@api_bp.route("/estructuras/estado", methods=["GET"])
def estado_estructuras():
    """GET /api/estructuras/estado"""
    return _json({
        "pila": {
            "tipo":      "Stack (LIFO)",
            "tamano":    pila_ventas.tamano(),
            "capacidad": pila_ventas._capacidad,
            "peek":      pila_ventas.peek(),
            "contenido": pila_ventas.to_list(),
        },
        "tabla_hash": {
            "tipo":      "Hash Table (encadenamiento)",
            "total":     tabla_productos.total(),
            "capacidad": tabla_productos._capacidad,
            "entradas":  tabla_productos.todos(),
        },
    })
