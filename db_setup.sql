-- FerreSmart Pro — Script SQL manual
-- Alternativa a la auto-inicialización de init_db()
-- Uso: mysql -u root -p < db_setup.sql

CREATE DATABASE IF NOT EXISTS ventas_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE ventas_db;

CREATE TABLE IF NOT EXISTS clientes (
    id          VARCHAR(10)  NOT NULL PRIMARY KEY,
    nombre      VARCHAR(100) NOT NULL,
    nit         VARCHAR(20)  DEFAULT 'CF',
    telefono    VARCHAR(20)  DEFAULT '',
    correo      VARCHAR(100) DEFAULT '',
    direccion   VARCHAR(200) DEFAULT '',
    creado_en   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS productos (
    id          VARCHAR(10)   NOT NULL PRIMARY KEY,
    nombre      VARCHAR(100)  NOT NULL,
    categoria   VARCHAR(60)   NOT NULL,
    precio      DECIMAL(10,2) NOT NULL,
    stock       INT           NOT NULL DEFAULT 0,
    unidad      VARCHAR(20)   DEFAULT 'unidad',
    activo      TINYINT(1)    NOT NULL DEFAULT 1,
    creado_en   TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

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
);
