# Std Library Imports:
from functools import wraps
import os
# 3rd-Party Imports:
from firebase_admin import credentials, auth, initialize_app
from flask import Flask, g, jsonify
from flask import request
from flask_cors import CORS
from flask_restful import Api
import google.auth.transport.requests as google_requests
from google.oauth2 import id_token
import requests

# Local Imports:


# Constants
ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5000")
HOST_SERVER = '0.0.0.0' # Bind to all interfaces (required for containers)
HOST_PORT = 8080
API_URLS = {
'account_api'   : os.getenv('ACCOUNT_API_URL',   'http://localhost:5001'),
'auth_api'      : os.getenv('AUTH_API_URL',      'http://localhost:5002'),
'billing_api'   : os.getenv('BILLING_API_URL',   'http://localhost:5003'),
'device_api'    : os.getenv('DEVICE_API_URL',    'http://localhost:5004'),
'embeddings_api': os.getenv('EMBEDDINGS_API_URL','http://localhost:5005'),
'image_api'     : os.getenv('IMAGE_API_URL',     'http://localhost:5006'),
'model_api'     : os.getenv('MODEL_API_URL',     'http://localhost:5007'),
'notification_api'  : os.getenv('NOTIFICATION_API_URL', 'http://localhost:5008'),
'recognition_api'   : os.getenv('RECOGNITION_API_URL',  'http://localhost:5009')
}



def create_app(test_config=None):
    """Creates and configures the Flask application instance for the API Gateway."""
    app = Flask(__name__, instance_relative_config=True)
    api = Api(app)
    register_routes(app) # Registers API Routes

    key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "../keys/gatewayApiServiceKey.json")
    if os.path.exists(key_path):
        cred = credentials.Certificate(key_path)
        firebase_app = initialize_app(cred)  # Initializes with explicit credentials
    else:
        firebase_app = initialize_app()  # Uses Application Default Credentials (Cloud Run)

    CORS(app, resources={r"/services/*":
                        {"origins": ORIGINS.split(","),
                        "methods": ["GET", "POST", "PATCH", "DELETE"],
                        "supports_credentials": True}
                        })

    return app


def get_identity_token(audience):
    """Fetches a Google identity token for service-to-service auth on Cloud Run."""
    try:
        token = id_token.fetch_id_token(google_requests.Request(), audience)
        return token
    except Exception:
        return None


def dispatcher(req_api:str, req_path:str, req_type:str='GET', json=None):

    url = f'{API_URLS[req_api]}{req_path}'
    audience = API_URLS[req_api]
    
    # Forward authenticated user identity to downstream services
    headers = {'X-User-Id': g.get('user_id', '')}

    # Attach identity token for Cloud Run service-to-service auth
    identity_token = get_identity_token(audience)
    if identity_token:
        headers['Authorization'] = f'Bearer {identity_token}'

    try:
        match req_type:
            case 'GET':
                response = requests.get(url, params=request.args.to_dict(), headers=headers)
            case 'POST':
                response = requests.post(url, json=json, headers=headers)
            case 'MULTIPART':
                files = {k: (f.filename or k, f.read(), f.content_type or 'application/octet-stream')
                         for k, f in request.files.items()}
                response = requests.post(url, data=request.form.to_dict(), files=files, headers=headers)
            case 'PATCH':
                response = requests.patch(url, json=json, headers=headers)
            case 'DELETE':
                response = requests.delete(url, params=request.args.to_dict(), headers=headers)
            case _:
                raise ValueError(f"Unsupported request type: {req_type}")

        return response.json(), response.status_code
    except Exception as e:
        return jsonify({"error": f'Dispatcher error: {str(e)}'}), 500



#   ----- Authentication Wrapper -----
def check_token(function):
    
    @wraps(function)
    def wrapper(*args, **kwargs):

        token = request.headers.get('Authorization')

        if not token:
            return jsonify({"error": "Authorization token is missing"}), 400
        
        # Strip "Bearer " prefix if present
        if token.startswith('Bearer '):
            token = token[7:]

        try:
            # Verify the token using Firebase Admin SDK
            decoded_token = auth.verify_id_token(token, None, True, 1)
            g.user = decoded_token
        except Exception as e:
            return jsonify({"error": "Invalid or expired token"}), 401
        
        g.user_id = decoded_token.get('uid')
    
        return function(*args, **kwargs)
    
    return wrapper


# Register Endpoint Routes
def register_routes(app):
    
    #   ----- Accounts API -----
    @app.route('/services/account',methods=['GET', 'POST', 'PATCH', 'DELETE'])
    @check_token
    def account():
        return dispatcher('account_api', '/account', request.method, request.get_json())
    
    #   ----- Device API -----
    #
    # 
    #
    #

    #   ----- Embeddings API -----
    @app.route('/services/embedding/get',methods=['GET'])
    @check_token
    def embedding_get(): # Admin Resource
        return dispatcher('embeddings_api', f'/embedding/get', request.method)
    # @app.route('/services/embedding/save',methods=['POST'])
    # @check_token
    # def embedding_save(): # Admin Resource
    #     return dispatcher('embeddings_api', '/embedding/save', request.method, request.get_json())
    @app.route('/services/embedding/update',methods=['PATCH'])
    @check_token
    def embedding_update(): # Admin Resource
        return dispatcher('embeddings_api', f'/embedding/update', request.method, request.get_json())
    @app.route('/services/embedding/delete',methods=['DELETE'])
    @check_token
    def embedding_delete(): # Admin Resource
        return dispatcher('embeddings_api', f'/embedding/delete', request.method)

    @app.route('/services/embedding/make/<string:uid>',methods=['POST'])
    @check_token
    def embedding_make(uid):
        return dispatcher('embeddings_api', f'/embedding/make/{uid}', 'MULTIPART')
    
    @app.route('/services/embedding/user/<string:uid>',methods=['GET','DELETE'])
    @check_token
    def embedding_user(uid):
        return dispatcher('embeddings_api', f'/embedding/user/{uid}', request.method)
    
    @app.route('/services/embedding/subject/<string:uid>',methods=['GET','DELETE'])
    @check_token
    def embedding_subject(uid):
        return dispatcher('embeddings_api', f'/embedding/subject/{uid}', request.method)


    #   ----- Image API -----
    @app.route('/services/image',methods=['GET', 'POST', 'PATCH', 'DELETE'])
    @check_token
    def image():
        return dispatcher('image_api', '/image', request.method, request.get_json())

    @app.route('/services/image_bulk',methods=['GET','DELETE'])
    @check_token
    def image_bulk():
        return dispatcher('image_api', '/image_bulk', request.method)

    @app.route('/services/image_subject',methods=['GET', 'PATCH', 'DELETE'])
    @check_token
    def image_subject():
        return dispatcher('image_api', '/image_subject', request.method, request.get_json())

    @app.route('/services/image_class',methods=['GET', 'PATCH'])
    @check_token
    def image_class():
        return dispatcher('image_api', '/image_class', request.method, request.get_json())

    #   ----- Notification API -----
    #
    # 
    #
    #

    #   ----- Recognition API -----
    @app.route('/services/recognition/process',methods=['POST'])
    @check_token
    def recognition_process(): # Admin Resource
        return dispatcher('recognition_api', '/process', request.method, request.get_json())



gateway_app = create_app() # Initializes the Flask App Instance

# Run App
if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("GATEWAY_PORT", HOST_PORT)))  # Cloud Run sets PORT
    gateway_app.run(host=HOST_SERVER, port=port)