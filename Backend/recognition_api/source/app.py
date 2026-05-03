"""
This module initializes an instance of the Model API. It handles the ML-model related endpoints and database interactions.

   To-Do:
        - Implement error handling

"""

# Std Library Imports:
import os

# 3rd-Party Imports:
from flask import Flask, app
from flask_restful import Api
from firebase_admin import credentials, initialize_app, firestore
from google.cloud.firestore_v1 import CollectionGroup
# Local Imports:

# Constants
HOST_SERVER = '0.0.0.0' # Bind to all interfaces (required for containers)
HOST_PORT = 8089 # Cloud Run default port


def create_app(test_config=None):
    """Creates and configures the Flask application instance for the Recognition API."""

    app = Flask(__name__, instance_relative_config=True)
    
    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    api = Api(app) # Initializes the Flask-RESTful API for the app
    api = register_routes(api) # Registers the endpoint routes for the API

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(base_dir, "keys", "recognitionApiServiceKey.json"))

    try:
        if os.path.exists(key_path):
            cred = credentials.Certificate(key_path)
            firebase_app = initialize_app(cred, { 'storageBucket' : 'ai-doorbell-c6bb9.firebasestorage.app'}, name='recognition_app')
        else:
            firebase_app = initialize_app(options={ 'storageBucket' : 'ai-doorbell-c6bb9.firebasestorage.app'}, name='recognition_app')  # Uses Application Default Credentials (Cloud Run)
    except ValueError:
        import firebase_admin
        firebase_app = firebase_admin.get_app('recognition_app')

    app.config['FIREBASE_APP'] = firebase_app # Adds the Firebase App Instance to the Flask App's configuration
    app.config['DATABASE_ID'] = "" # Adds the Firestore Database ID to the Flask App's configuration
    firebase_database = firestore.client(app.config['FIREBASE_APP'], app.config['DATABASE_ID']) # Connects to the Firestore Database
    app.config['FIRESTORE_DB'] = firebase_database # Adds the Firestore Database Client to the Flask App's configuration

    # Pre-warm DeepFace models so first inference doesn't hang in a background thread
    _prewarm_models()

    setup_listeners(app) # Sets up Firestore listeners for real-time updates

    return app


def _prewarm_models():
    """Load ArcFace + RetinaFace models eagerly so background threads never block on first load."""
    import numpy as np
    from deepface import DeepFace
    print("Pre-warming DeepFace models (ArcFace + RetinaFace)...", flush=True)
    try:
        dummy = np.zeros((112, 112, 3), dtype=np.uint8)
        DeepFace.represent(img_path=dummy, model_name="ArcFace",
                           detector_backend="skip", enforce_detection=False)
        DeepFace.extract_faces(img_path=dummy, detector_backend="retinaface",
                               enforce_detection=False)
        print("DeepFace models pre-warmed successfully.", flush=True)
    except Exception as e:
        print(f"WARNING: model pre-warm failed: {e}", flush=True)

# Register Endpoint Routes
def register_routes(api:Api):
    from source import resources
    api.add_resource(resources.NewEvent,('/process/<string:uid>'))
    api.add_resource(resources.CompareFaces, ('/compare')) # added in as an endpoint for testing purposes
    return api

# Starts a listener on the Events Collection in Firestore to watch for new events and trigger processing
def setup_listeners(app:Flask):
    from source import resources
    resources.flask_app = app # Make the Flask app available in resources.py for app_context() in background threads
    events_collection_group : CollectionGroup = app.config['FIRESTORE_DB'].collection_group('events')
    app.config['EVENTS_LISTENER'] = events_collection_group.on_snapshot(resources.collection_listener)

flask_app = create_app() # Initializes the Flask App Instance

# Run App
if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("RECOGNITION_PORT", HOST_PORT)))  # Cloud Run sets PORT
    flask_app.run(host = HOST_SERVER, port = port)
