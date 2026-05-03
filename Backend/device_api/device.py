from flask import current_app, Blueprint, request, jsonify
from db import get_db

from firebase_init import db

bp = Blueprint('device', __name__, url_prefix='/device/api')  


@bp.route('/list', methods=['GET'])
def list_devices():
    db = get_db()
    rows = db.execute('SELECT * FROM device').fetchall()
    return jsonify([dict(row) for row in rows])


@bp.route('/<int:device_id>', methods=['GET'])
def get_device(device_id):
    db = get_db()
    row = db.execute('SELECT * FROM device WHERE id = ?', (device_id,)).fetchone()

    if row is None:
        return jsonify({"error": "Device not found"}), 404

    return jsonify(dict(row))