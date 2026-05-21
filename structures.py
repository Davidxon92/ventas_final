"""
Estructuras de datos personalizadas para FerreSmart Pro.

Correcciones aplicadas:
  - PilaVentas ahora usa collections.deque(maxlen=N) internamente.
    Antes usaba list.pop(0) para desalojar el elemento más antiguo,
    lo que es O(n) y conceptualmente convierte la estructura en una
    dequeue, no en una pila LIFO. Con deque(maxlen) el descarte es O(1)
    y se mantiene el semántico de "ventana deslizante de ventas recientes".
  - La capacidad por defecto de __init__ (20) y la instancia global (10)
    estaban inconsistentes. Se unifica en 10 en ambos lugares.
  - cargar_desde_lista() respeta self._capacidad en vez de usar
    un slice hardcodeado a 10 en routes.py.
  - TablaHashProductos sin cambios — implementación correcta.
"""

from collections import deque


# ─────────────────────────────────────────────
#  PILA  (Stack) – Ventas Recientes
# ─────────────────────────────────────────────

class PilaVentas:
    """
    Pila LIFO para almacenar las ventas más recientes.

    Internamente usa collections.deque(maxlen=capacidad):
      - push / pop / peek son O(1).
      - Cuando la pila está llena y se hace push, el elemento más
        antiguo (el primero que entró) se descarta automáticamente,
        manteniendo el semántico de "ventana deslizante".
    """

    def __init__(self, capacidad: int = 10):
        self._capacidad: int = capacidad
        self._datos: deque = deque(maxlen=capacidad)

    # ── Operaciones básicas ──────────────────

    def push(self, venta: dict) -> None:
        """Agrega una venta a la cima de la pila."""
        self._datos.append(venta)          # deque descarta el más antiguo automáticamente si maxlen se supera

    def pop(self) -> dict | None:
        """Extrae y retorna la venta en la cima (más reciente)."""
        if self.esta_vacia():
            return None
        return self._datos.pop()

    def peek(self) -> dict | None:
        """Consulta la venta en la cima sin extraerla."""
        if self.esta_vacia():
            return None
        return self._datos[-1]

    # ── Utilidades ───────────────────────────

    def esta_vacia(self) -> bool:
        return len(self._datos) == 0

    def tamano(self) -> int:
        return len(self._datos)

    def to_list(self) -> list:
        """Retorna todas las ventas en orden LIFO (más reciente primero)."""
        return list(reversed(self._datos))

    def limpiar(self) -> None:
        self._datos.clear()

    def cargar_desde_lista(self, ventas: list) -> None:
        """
        Carga una lista de ventas en la pila (reemplaza el contenido previo).
        Respeta self._capacidad en vez de un slice hardcodeado.
        """
        self.limpiar()
        for v in ventas[:self._capacidad]:
            self.push(v)

    def __repr__(self):
        return f"PilaVentas(tamaño={self.tamano()}, capacidad={self._capacidad})"


# ─────────────────────────────────────────────
#  TABLA HASH – Productos
# ─────────────────────────────────────────────

class TablaHashProductos:
    """
    Tabla hash para consultas O(1) de productos por código.
    Implementación manual con encadenamiento para resolución de colisiones.
    Sin cambios respecto a la versión original — implementación correcta.
    """

    def __init__(self, capacidad: int = 64):
        self._capacidad: int = capacidad
        self._buckets: list = [[] for _ in range(capacidad)]
        self._total: int = 0

    # ── Función hash ─────────────────────────

    def _hash(self, clave: str) -> int:
        """Polinomial rolling hash sobre los caracteres de la clave."""
        h, base, mod = 0, 31, self._capacidad
        for c in clave.upper():
            h = (h * base + ord(c)) % mod
        return h

    # ── Operaciones básicas ──────────────────

    def insertar(self, codigo: str, producto: dict) -> None:
        """Inserta o actualiza un producto por su código."""
        idx = self._hash(codigo)
        bucket = self._buckets[idx]
        for i, (k, _) in enumerate(bucket):
            if k == codigo.upper():
                bucket[i] = (codigo.upper(), producto)
                return
        bucket.append((codigo.upper(), producto))
        self._total += 1

    def buscar(self, codigo: str) -> dict | None:
        """Retorna el producto o None si no existe."""
        idx = self._hash(codigo)
        for k, v in self._buckets[idx]:
            if k == codigo.upper():
                return v
        return None

    def eliminar(self, codigo: str) -> bool:
        """Elimina un producto. Retorna True si fue encontrado."""
        idx = self._hash(codigo)
        bucket = self._buckets[idx]
        for i, (k, _) in enumerate(bucket):
            if k == codigo.upper():
                bucket.pop(i)
                self._total -= 1
                return True
        return False

    # ── Utilidades ───────────────────────────

    def todos(self) -> list:
        """Retorna todos los productos como lista de dicts."""
        resultado = []
        for bucket in self._buckets:
            for _, v in bucket:
                resultado.append(v)
        return resultado

    def existe(self, codigo: str) -> bool:
        return self.buscar(codigo) is not None

    def total(self) -> int:
        return self._total

    def limpiar(self) -> None:
        self._buckets = [[] for _ in range(self._capacidad)]
        self._total = 0

    def cargar_desde_lista(self, productos: list) -> None:
        """Carga una lista de productos en la tabla hash."""
        self.limpiar()
        for p in productos:
            self.insertar(p["id"], p)

    def __repr__(self):
        return f"TablaHashProductos(total={self._total}, capacidad={self._capacidad})"


# ─────────────────────────────────────────────
#  Instancias globales (Singleton por proceso)
# ─────────────────────────────────────────────

pila_ventas     = PilaVentas(capacidad=10)
tabla_productos = TablaHashProductos(capacidad=64)
