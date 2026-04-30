"""
API Server para exportar datos de la BD a CSV/JSON.
Permite conectar Power BI u otras herramientas de BI.
"""
import os
import io
import re
import csv
import sqlite3
import logging
from datetime import datetime
from flask import Flask, Response, jsonify, request

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_PATH = os.getenv('DB_PATH', '/app/data/bot.db')
API_KEY = os.getenv('API_KEY', 'claro2026')
API_PORT = int(os.getenv('API_PORT', '5000'))
PIN_FILE = '/app/data/pin.txt'

app = Flask(__name__)


def check_api_key():
    """Verificar API key en header o query param"""
    key = request.headers.get('X-API-Key') or request.args.get('api_key')
    if key != API_KEY:
        return False
    return True


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def rows_to_csv(rows, columns):
    """Convierte filas de SQLite a string CSV"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row[col] for col in columns])
    return output.getvalue()


# ──────────────────────────────────────────────
#  ENDPOINTS CSV
# ──────────────────────────────────────────────

@app.route('/')
def index():
    return jsonify({
        "servicio": "Claro Bot Agenda - API de Datos",
        "endpoints": {
            "/csv/operaciones": "Log de operaciones (CSV)",
            "/csv/usuarios": "Usuarios autorizados (CSV)",
            "/csv/reporte": "Reporte completo con nombres (CSV)",
            "/json/operaciones": "Log de operaciones (JSON)",
            "/json/usuarios": "Usuarios autorizados (JSON)",
            "/json/estadisticas": "Estadísticas generales (JSON)",
            "/api/sms_pin": "POST - Recibe SMS y extrae PIN para login automático",
        },
        "autenticacion": "Enviar api_key como query param o header X-API-Key"
    })


@app.route('/csv/operaciones')
def csv_operaciones():
    if not check_api_key():
        return Response("No autorizado", status=401)

    fecha_desde = request.args.get('desde', '')
    fecha_hasta = request.args.get('hasta', '')

    conn = get_db()
    query = "SELECT id, chat_id, orden, resultado, detalle, fecha FROM log_operaciones"
    params = []
    conditions = []

    if fecha_desde:
        conditions.append("fecha >= ?")
        params.append(fecha_desde)
    if fecha_hasta:
        conditions.append("fecha <= ?")
        params.append(fecha_hasta)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY fecha DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    columns = ['id', 'chat_id', 'orden', 'resultado', 'detalle', 'fecha']
    csv_data = rows_to_csv(rows, columns)

    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=operaciones.csv'}
    )


@app.route('/csv/usuarios')
def csv_usuarios():
    if not check_api_key():
        return Response("No autorizado", status=401)

    conn = get_db()
    rows = conn.execute(
        "SELECT chat_id, nombre, activo, fecha_registro FROM usuarios_autorizados"
    ).fetchall()
    conn.close()

    columns = ['chat_id', 'nombre', 'activo', 'fecha_registro']
    csv_data = rows_to_csv(rows, columns)

    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=usuarios.csv'}
    )


@app.route('/csv/reporte')
def csv_reporte():
    """Reporte combinado: operaciones con nombre del usuario"""
    if not check_api_key():
        return Response("No autorizado", status=401)

    fecha_desde = request.args.get('desde', '')
    fecha_hasta = request.args.get('hasta', '')

    conn = get_db()
    query = """
        SELECT
            o.id,
            o.chat_id,
            COALESCE(u.nombre, 'Desconocido') as usuario,
            o.orden,
            o.resultado,
            o.detalle,
            o.fecha
        FROM log_operaciones o
        LEFT JOIN usuarios_autorizados u ON o.chat_id = u.chat_id
    """
    params = []
    conditions = []

    if fecha_desde:
        conditions.append("o.fecha >= ?")
        params.append(fecha_desde)
    if fecha_hasta:
        conditions.append("o.fecha <= ?")
        params.append(fecha_hasta)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY o.fecha DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    columns = ['id', 'chat_id', 'usuario', 'orden', 'resultado', 'detalle', 'fecha']
    csv_data = rows_to_csv(rows, columns)

    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=reporte.csv'}
    )


# ──────────────────────────────────────────────
#  ENDPOINTS JSON
# ──────────────────────────────────────────────

@app.route('/json/operaciones')
def json_operaciones():
    if not check_api_key():
        return jsonify({"error": "No autorizado"}), 401

    fecha_desde = request.args.get('desde', '')
    fecha_hasta = request.args.get('hasta', '')

    conn = get_db()
    query = "SELECT id, chat_id, orden, resultado, detalle, fecha FROM log_operaciones"
    params = []
    conditions = []

    if fecha_desde:
        conditions.append("fecha >= ?")
        params.append(fecha_desde)
    if fecha_hasta:
        conditions.append("fecha <= ?")
        params.append(fecha_hasta)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY fecha DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    data = [dict(row) for row in rows]
    return jsonify({"total": len(data), "datos": data})


@app.route('/json/usuarios')
def json_usuarios():
    if not check_api_key():
        return jsonify({"error": "No autorizado"}), 401

    conn = get_db()
    rows = conn.execute(
        "SELECT chat_id, nombre, activo, fecha_registro FROM usuarios_autorizados"
    ).fetchall()
    conn.close()

    data = [dict(row) for row in rows]
    return jsonify({"total": len(data), "datos": data})


@app.route('/json/estadisticas')
def json_estadisticas():
    if not check_api_key():
        return jsonify({"error": "No autorizado"}), 401

    conn = get_db()

    total = conn.execute("SELECT COUNT(*) FROM log_operaciones").fetchone()[0]
    exitosas = conn.execute(
        "SELECT COUNT(*) FROM log_operaciones WHERE resultado = 'exito'"
    ).fetchone()[0]
    fallidas = conn.execute(
        "SELECT COUNT(*) FROM log_operaciones WHERE resultado = 'error'"
    ).fetchone()[0]

    # Operaciones por usuario
    por_usuario = conn.execute("""
        SELECT
            o.chat_id,
            COALESCE(u.nombre, 'Desconocido') as usuario,
            COUNT(*) as total,
            SUM(CASE WHEN o.resultado = 'exito' THEN 1 ELSE 0 END) as exitosas,
            SUM(CASE WHEN o.resultado = 'error' THEN 1 ELSE 0 END) as fallidas
        FROM log_operaciones o
        LEFT JOIN usuarios_autorizados u ON o.chat_id = u.chat_id
        GROUP BY o.chat_id
    """).fetchall()

    # Operaciones por día (últimos 30 días)
    por_dia = conn.execute("""
        SELECT
            DATE(fecha) as dia,
            COUNT(*) as total,
            SUM(CASE WHEN resultado = 'exito' THEN 1 ELSE 0 END) as exitosas
        FROM log_operaciones
        WHERE fecha >= DATE('now', '-30 days')
        GROUP BY DATE(fecha)
        ORDER BY dia DESC
    """).fetchall()

    conn.close()

    return jsonify({
        "resumen": {
            "total_operaciones": total,
            "exitosas": exitosas,
            "fallidas": fallidas,
            "tasa_exito": f"{(exitosas/total*100):.1f}%" if total > 0 else "N/A"
        },
        "por_usuario": [dict(row) for row in por_usuario],
        "por_dia": [dict(row) for row in por_dia]
    })


# ──────────────────────────────────────────────
#  ENDPOINT PIN SMS (para automatización iPhone)
# ──────────────────────────────────────────────

@app.route('/api/sms_pin', methods=['POST'])
def sms_pin():
    """Recibe el texto del SMS desde iPhone y extrae el PIN.
    
    Acepta:
    - JSON: {"text": "Tu codigo de acceso es: 849415"}
    - Form: text=Tu+codigo+de+acceso+es:+849415
    - Query: ?text=Tu+codigo+de+acceso+es:+849415&api_key=claro2026
    """
    if not check_api_key():
        return jsonify({"error": "No autorizado"}), 401

    # Obtener texto del SMS
    texto = None
    if request.is_json:
        texto = request.json.get('text', '')
    elif request.form:
        texto = request.form.get('text', '')
    else:
        texto = request.args.get('text', '')

    if not texto:
        return jsonify({"error": "No se recibió texto", "uso": "POST con text=<sms>"}), 400

    logger.info(f"SMS recibido: {texto}")

    # Extraer PIN del texto
    pin_match = re.search(r'(\d{4,6})\s*$', texto)
    if not pin_match:
        pin_match = re.search(r'(\d{4,6})', texto)

    if not pin_match:
        logger.warning(f"No se encontró PIN en: {texto}")
        return jsonify({"error": "No se encontró PIN en el texto", "texto": texto}), 400

    pin = pin_match.group(1)
    logger.info(f"PIN extraído: {pin}")

    # Escribir PIN al archivo compartido
    try:
        with open(PIN_FILE, 'w') as f:
            f.write(pin)
        logger.info(f"PIN {pin} escrito en {PIN_FILE}")
        return jsonify({"ok": True, "pin": pin, "mensaje": f"PIN {pin} enviado al bot"})
    except Exception as e:
        logger.error(f"Error escribiendo PIN: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    logger.info(f"API Server iniciando en puerto {API_PORT}...")
    logger.info(f"Base de datos: {DB_PATH}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False)
