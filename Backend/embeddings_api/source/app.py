"""
This module initializes an instance of the Embedding API. It handles the ML-Embedding related endpoints and database interactions.

   To-Do:
        - Implement error handling
 
   Functions:
        - create_app()
"""

# Std Library Imports:
import os

# 3rd-Party Imports:
from flask import Flask
from flask_restful import Api
from firebase_admin import credentials, initialize_app, firestore
from google.cloud.firestore_v1 import CollectionGroup

# Local Imports:

# Constants
HOST_SERVER = '0.0.0.0' # Bind to all interfaces (required for containers)
HOST_PORT = 8085 # Cloud Run default port

def create_app(test_config=None):
    """Creates and configures the Flask application instance for the Embedding API."""

    app = Flask(__name__, instance_relative_config=True)
    
    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    api = Api(app)          # Initializes the Flask-RESTful API for the app
    api = register_routes(api)  # Registers the endpoint routes for the API
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(base_dir, "keys", "embeddingsApiServiceKey.json"))

    try:
        if os.path.exists(key_path):
            cred = credentials.Certificate(key_path)
            firebase_app = initialize_app(cred, name='embeddings_app')  # Initializes with explicit credentials
        else:
            firebase_app = initialize_app(name='embeddings_app')  # Uses Application Default Credentials (Cloud Run)
    except ValueError:
        import firebase_admin
        firebase_app = firebase_admin.get_app('embeddings_app')

    app.config['FIREBASE_APP'] = firebase_app # Adds the Firebase App Instance to the Flask App's configuration
    app.config['DATABASE_ID'] = "" # Adds the Firestore Database ID to the Flask App's configuration
    firebase_database = firestore.client(app.config['FIREBASE_APP'], app.config['DATABASE_ID']) # Connects to the Firestore Database
    app.config['FIRESTORE_DB'] = firebase_database # Adds the Firestore Database Client to the Flask App's configuration
    
    setup_listeners(app) # Sets up Firestore listeners for real-time updates

    return app

# Register Endpoint Routes
def register_routes(api):
    from source import resources
    api.add_resource(resources.GetEmbedding,        ('/embedding/get'))
    api.add_resource(resources.PostEmbedding,       ('/embedding/post'))
    api.add_resource(resources.UpdateEmbedding,     ('/embedding/update'))
    api.add_resource(resources.DeleteEmbedding,     ('/embedding/delete'))
    api.add_resource(resources.MakeEmbedding,       ('/embedding/make/<string:uid>'))
    api.add_resource(resources.UserEmbeddings,      ('/embedding/user/<string:uid>'))
    api.add_resource(resources.SubjectEmbeddings,   ('/embedding/subject/<string:uid>'))
    return api

# Starts a listener on the Events Collection in Firestore to watch for new events and trigger processing
def setup_listeners(app:Flask):
    from source import resources
    resources.flask_app = app # Make the Flask app available in resources.py for app_context() in background threads
    faces_collection_group : CollectionGroup = app.config['FIRESTORE_DB'].collection_group('faces')
    app.config['EVENTS_LISTENER'] = faces_collection_group.on_snapshot(resources.collection_listener)


flask_app = create_app() # Initializes the Flask App Instance

# Runs the Flask App
if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("EMBEDDINGS_PORT", HOST_PORT)))  # Cloud Run sets PORT
    flask_app.run(host = HOST_SERVER, port=port)

