"""
This module initializes an instance of the Device API.

   To-Do:
        - Implement error handling
 
   Functions:
        - create_app()
"""

from datetime import datetime

# Std Library Imports:
import os

# 3rd-Party Imports:
from flask import Flask, request, render_template, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager,create_access_token, get_jwt_identity,jwt_required

import sqlite3
from firebase_init import db as firestore_db

#import firebase_admin # Import later when integrating with the database

# Local Imports:
import db #maybe not necessary
from db import get_db

# import auth #not relevent to us



def create_app(test_config=None):
    """Creates and configures the Flask application instance for the Device API."""
    
    app = Flask(__name__, instance_relative_config=True) # Here we create an instance of Flask class
    app.config.from_mapping(
        SECRET_KEY='dev',
        DATABASE=os.path.join(app.instance_path, 'app.sqlite'),
    )

    
    """if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)"""

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass
    

    # Root URL
    @app.route('/', methods=['GET'])
    def index():
        return "<h1>Device API Home</h1>"
    
    # Dashboard
    """ This was for local SQL before, but we are using Firestore now 
    @app.route('/dashboard', methods=['GET'])
    def dashboard():
        
        db_conn = get_db()
        #db_conn = db.get_db()  # get the database connection

        devices = db_conn.execute('SELECT * FROM device').fetchall()  # fetch all devices
        return render_template('dashboard.html', devices=devices)
    """

    # we now fetch all documents from the "devices" collection in Firestore and pass them to the dashboard template
    @app.route('/dashboard', methods=['GET'])
    def dashboard():

        devices_ref = firestore_db.collection("devices")
        docs = devices_ref.stream()

        devices = []
        for doc in docs:
            device = doc.to_dict()
            device["id"] = doc.id
            devices.append(device)

        return render_template('dashboard.html', devices=devices)
    
    # Database setup: Telling database module to register itself with this Flask app
    db.init_app(app)


    # Route to handle device registration
    @app.route('/device/register', methods=['GET', 'POST'])
    def register_device():
        db_conn = get_db()

        if request.method == 'POST':
            serial_number = request.form['serial_number']
            user_id = int(request.form['user_id'])

            """ # This is what I needed for SQLLite database, but not for Firestore
            try:
                db_conn.execute(
                    'INSERT INTO device (serial_number, user_id) VALUES (?, ?)',
                    (serial_number, user_id)
                )
                db_conn.commit()
                return "Device registered successfully! <a href='/dashboard'>Back</a>"

                return "Device registered successfully in Firestore! <a href='/dashboard'>Back</a>"
            
            except sqlite3.IntegrityError as e:
                return f"Database error: {str(e)}"
            """
            # This change is for it to work for Firestore

            try:
                device_data = {
                    "serial_number": serial_number,
                    "user_id": user_id,
                    "registered_at": datetime.utcnow().isoformat()
                }

                # Naming the document in Firestore as the serial number of the device
                firestore_db.collection("devices").document(serial_number).set(device_data)

                return "Device registered successfully in Firestore! <a href='/dashboard'>Back</a>"

            except Exception as e:
                return f"Firestore error: {str(e)}"

        return render_template('register_device.html')

    from device import bp as device_bp
    app.register_blueprint(device_bp)

    return app

if __name__ == "__main__":
    app = create_app()
    app.run()
