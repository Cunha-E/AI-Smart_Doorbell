"""
This module initializes an instance of the Image API. It handles the image-related endpoints and database interactions.

   To-Do:
        - Implement error handling
"""


# Std Library Imports:
import os

# 3rd-Party Imports:
from flask import Flask, current_app
from flask_restful import Api
from firebase_admin import credentials, firestore, initialize_app

# Local Imports:
import resources


# Constants
HOST_SERVER = '127.0.0.1' # Set to local host while in development
HOST_PORT = 5006

# Creates and configures the Flask application instance for the Image API.
def create_app(test_config=None):
    """Creates and configures the Flask application instance for the Image API."""
    
    app = Flask(__name__, instance_relative_config=True)
    
    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    api = Api(app)          # Initializes the Flask-RESTful API for the app
    api = register_routes(api)  # Registers the endpoint routes for the API


    cred = credentials.Certificate("../keys/imageApiServiceKey.json")
    firebase_app = initialize_app(cred, { 'storageBucket' : 'ai-doorbell-c6bb9.firebasestorage.app/api/image_bucket'}) # Initializes the Firebase App Instance
    app.config['FIREBASE_APP'] = firebase_app # Adds the Firebase App Instance to the Flask App's configuration
    app.config['DATABASE_ID'] = "" # Adds the Firestore Database ID to the Flask App's configuration
    app.config['FIRESTORE_DB'] = firestore.client(app.config['FIREBASE_APP'], app.config['DATABASE_ID']) # Connects to the Firestore Database

    return app

# Register Endpoint Routes
def register_routes(api):
    api.add_resource(resources.Image,        ('/image'))
    api.add_resource(resources.ImageBulk,       ('/image_bulk'))
    api.add_resource(resources.ImageSubject,     ('/image_subject'))
    api.add_resource(resources.ImageClass,     ('/image_class'))
    return api

# Creates the Flask App
flask_app = create_app() # Initializes the Flask App Instance

# Configures the ports and runs the App
if __name__ == "__main__":
    port = int(os.getenv("IMAGE_PORT", HOST_PORT))
    host = os.getenv("IMAGE_URL", HOST_SERVER)
    flask_app.run(host = host, port=port)

def get_db():
    """
    Retrieves the connection to the Firestore Database.
    """
    return current_app.config['FIRESTORE_DB']
