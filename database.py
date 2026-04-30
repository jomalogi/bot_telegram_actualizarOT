import sqlite3
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.getenv('DB_PATH', '/app/data/bot.db')

class Database:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(DB_PATH)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS usuarios_autorizados (
                    chat_id INTEGER PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    activo INTEGER DEFAULT 1,
                    fecha_registro TEXT DEFAULT (datetime('now'))
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS log_operaciones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    orden TEXT,
                    resultado TEXT,
                    detalle TEXT,
                    fecha TEXT DEFAULT (datetime('now'))
                )
            ''')
            conn.commit()
        logger.info(f"Base de datos inicializada en {DB_PATH}")

    def is_user_authorized(self, chat_id: int) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                'SELECT activo FROM usuarios_autorizados WHERE chat_id = ? AND activo = 1',
                (chat_id,)
            ).fetchone()
        return row is not None

    def add_user(self, chat_id: int, nombre: str):
        with self._get_conn() as conn:
            conn.execute(
                '''INSERT INTO usuarios_autorizados (chat_id, nombre, activo)
                   VALUES (?, ?, 1)
                   ON CONFLICT(chat_id) DO UPDATE SET nombre=excluded.nombre, activo=1''',
                (chat_id, nombre)
            )
            conn.commit()
        logger.info(f"Usuario agregado: {nombre} ({chat_id})")

    def remove_user(self, chat_id: int):
        with self._get_conn() as conn:
            conn.execute(
                'UPDATE usuarios_autorizados SET activo = 0 WHERE chat_id = ?',
                (chat_id,)
            )
            conn.commit()
        logger.info(f"Usuario desactivado: {chat_id}")

    def list_users(self) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                'SELECT chat_id, nombre, fecha_registro FROM usuarios_autorizados WHERE activo = 1'
            ).fetchall()
        return [{'chat_id': r[0], 'nombre': r[1], 'fecha': r[2]} for r in rows]

    def log_operacion(self, chat_id: int, orden: str, resultado: str, detalle: str = ''):
        with self._get_conn() as conn:
            conn.execute(
                'INSERT INTO log_operaciones (chat_id, orden, resultado, detalle) VALUES (?, ?, ?, ?)',
                (chat_id, orden, resultado, detalle)
            )
            conn.commit()
