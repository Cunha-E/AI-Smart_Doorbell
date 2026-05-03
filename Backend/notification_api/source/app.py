"""
This module initializes an instance of the Notification API. It handles the the routes and Firestore operations used to create notification event documents.

   To-Do:
   Functions:
        - create_app() 
        - register_routes()
        
        - home()
        - test_dashboard()
"""

# Std Library Imports:
import os

# 3rd-Party Imports:
from flask import Flask, render_template #for html testing 
from flask_restful import Api
from firebase_admin import credentials, initialize_app, firestore, storage

# Local Imports:

# Constants
HOST_SERVER = '0.0.0.0' # Bind to all interfaces (required for containers)
HOST_PORT = 8088 

def create_app(test_config=None):
    """Creates and configures the Flask application instance for the Notification API.
       Uses the folder named "templates" for HTML files
    """

    app = Flask(__name__, instance_relative_config=True, template_folder="templates") 
    
    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    api = Api(app)          # Initializes the Flask-RESTful API for the app
    api = register_routes(api)  # Registers the endpoint routes for the API

    @app.route("/")  # Communicates to Flask that the function below should run when the root URL "/" is visited.
    def home():
        return "Notification API is running"
    
    @app.route("/dashboard")
    def test_dashboard():
        return render_template("dashboard.html")
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(base_dir, "keys", "notificationApiServiceKey.json"))
    bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET", "ai-doorbell-c6bb9.firebasestorage.app") #Will use .env to avoid hardcoding later
    try:
        if os.path.exists(key_path):
            cred = credentials.Certificate(key_path)
            firebase_app = initialize_app(cred, {"storageBucket": bucket_name}, name='notification_app')
        else:
            firebase_app = initialize_app(options={"storageBucket": bucket_name}, name='notification_app')  # Uses Application Default Credentials (Cloud Run)
    except ValueError:
        # App already initialized (e.g. during testing)
        import firebase_admin
        firebase_app = firebase_admin.get_app('notification_app')
    app.config['FIREBASE_APP'] = firebase_app # Adds the Firebase App Instance to the Flask App's configuration
    app.config['DATABASE_ID'] = "" # Adds the Firestore Database ID to the Flask App's configuration
    app.config['FIRESTORE_DB'] = firestore.client(app.config['FIREBASE_APP'], app.config['DATABASE_ID']) # Connects to the Firestore Database
    app.config["STORAGE_BUCKET"] = storage.bucket(app=firebase_app) #Connects to storage buckets

    from source import resources
    resources.flask_app = app # Make the Flask app available in resources.py for app_context()
    
    return app

# Register Endpoint Routes
def register_routes(api):
    from source import resources # Imports the resource classes from resources.py.
    api.add_resource(resources.Notify, "/notify") # Connects the Notify resource to the /notify URL.
    return api

flask_app = create_app() # Initializes the Flask App Instance

# Runs the Flask App
if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("NOTIFICATION_PORT", HOST_PORT)))  # Cloud Run sets PORT
    flask_app.run(host = HOST_SERVER, port=port)

