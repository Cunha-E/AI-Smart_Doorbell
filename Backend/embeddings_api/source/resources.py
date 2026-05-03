"""
This module handles resources/logic used by the Embedding API.

   To-Do:
        - Implement error handling
        - Test Embedding object conversions when messaging between Embedding API and other APIs
   Resources:
        - Embeddings
        - Embedding (Database Model)
"""

# Std Library Imports:
from datetime import datetime, timezone
import logging
import os
import uuid
import json
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

# 3rd-Party Imports:
from flask import Flask, request, current_app
from flask_restful import Resource
from deepface import DeepFace
from PIL import Image
import numpy
import google.auth.transport.requests as google_requests
from google.oauth2 import id_token
from google.cloud.firestore_v1.base_document import DocumentSnapshot, BaseDocumentReference
from google.cloud.firestore_v1.base_collection import BaseCollectionReference
from google.cloud.firestore_v1.watch import DocumentChange
from google.api_core.datetime_helpers import DatetimeWithNanoseconds
from google.cloud.firestore_v1 import CollectionGroup, DocumentReference
from google.cloud.firestore_v1 import Client
# Local Imports:

# CONSTANTS:
MATCH_THRESHOLD = 0.6 # Threshold for embedding matches (lower is more strict, higher is more lenient)
K_INCLUSION_THRESHOLD = 0.4 # Threshold for whether a face is included in the K-matches returned by find_batched() (lower is more strict, higher is more lenient)
UPDATE_EMBEDDING_THRESHOLD = 0.5 # Threshold for whether to update an existing embedding with a new detected face (lower is more strict, higher is more lenient)
DEFAULT_DETECTOR = os.getenv("DEFAULT_DETECTOR_BACKEND", "retinaface") # Detector backend for DeepFace (retinaface is best, but can be changed for testing purposes)
DEFAULT_MODEL = os.getenv("DEFAULT_RECOGNITION_MODEL", "ArcFace") # Model used to generate embeddings (must be consistent with the model used in the Embeddings API)
MAX_THREADS = 3 # Max threads for concurrent processing of faces (2 CPU cores | 2Gb RAM on Cloud Run)
ALLOWED_MODELS = {}
BACKUP_MODEL_LIST = {
    "facial_recognition":
    [
        "VGG-Face", "Facenet", "Facenet512","OpenFace",
        "DeepFace","DeepID", "Dlib","ArcFace","SFace",
        "GhostFaceNet", "Buffalo_L",
    ],
    "face_detector":
    [
        'opencv', 'retinaface', 'mtcnn', 'ssd', 'dlib',
        'mediapipe','yolov8n', 'yolov8m', 'yolov8l', 'yolov11n',
        'yolov11s','yolov11m', 'yolov11l', 'yolov12n', 'yolov12s',
        'yolov12m','yolov12l','yunet','fastmtcnn','centerface',
    ]
}

try:
    ALLOWED_MODELS = DeepFace.modeling.AVAILABLE_MODELS
except AttributeError:
    ALLOWED_MODELS = BACKUP_MODEL_LIST

threader = ThreadPoolExecutor(max_workers=MAX_THREADS) # ThreadPoolExecutor for concurrent processing
flask_app: Flask = None  # type: ignore  # Set by setup_listeners() in app.py
_listener_initialized = False # Flag to skip initial snapshot from on_snapshot

def _thread_error_callback(future):
    """Callback to log exceptions from background threads that would otherwise be silently swallowed."""
    exc = future.exception()
    if exc:
        logging.exception("Background thread error: %s", exc, exc_info=exc)

def get_service_headers(audience):
    """Build headers with identity token for Cloud Run service-to-service auth."""
    headers = {}
    try:
        token = id_token.fetch_id_token(google_requests.Request(), audience)
        headers['Authorization'] = f'Bearer {token}'
    except Exception:
        pass
    return headers


# Listens to Collection : devices/{device_id}/faces/{face_id}
def collection_listener(snapshot:list[DocumentSnapshot], changes:list[DocumentChange], read_time:DatetimeWithNanoseconds):
        # This function watches for changes in the Faces Collection
        global _listener_initialized
        
        if not _listener_initialized:
            # Skip initial snapshot — on_snapshot fires with ALL existing documents as MODIFIED on first call
            _listener_initialized = True
            print(f'Listener initialized, skipping {len(changes)} existing events.')
            return

        if snapshot is not None:
            for change in changes:
                if change.type.name == 'MODIFIED':
                    doc:DocumentSnapshot = change.document
                    print(f'New event detected: {doc.id}')
                    # Now process the new event
                    future = threader.submit(process_new_event, doc)
                    future.add_done_callback(_thread_error_callback)
        return

def process_new_event(doc: DocumentSnapshot):
    """Processes a MODIFIED face document event and updates associated embeddings."""
    with flask_app.app_context():
        face_data = doc.to_dict()
        if not face_data:
            logging.warning(f"Face document {doc.id} has no data, skipping.")
            return

        status = str(face_data.get("status") or "").strip().lower()
        subject_id = str(face_data.get("subject_id") or face_data.get("name") or "").strip().lower()
        event_id = doc.id

        # devices/{device_id}/faces/{face_id}
        parent_ref: DocumentReference = doc.reference.parent
        device_ref: DocumentReference = parent_ref.parent
        user_id = device_ref.id

        database: Client = current_app.config["FIRESTORE_DB"]

        try:
            # Find the embedding tied to this exact face/event
            linked_query = (
                database.collection("embeddings")
                .where("event_id", "==", event_id)
                .where("user_id", "==", user_id)
                .limit(1)
            )
            linked_results = list(linked_query.stream())

            if not linked_results:
                logging.warning(f"Embedding not found for face {doc.id}")
                return

            linked_embedding = linked_results[0]

            if status == "known" and subject_id:
                linked_embedding.reference.update({
                    "subject_id": subject_id,
                    "status": "known",
                })
                logging.info(f"Embedding {linked_embedding.id} updated: subject_id -> '{subject_id}'")
                return

            if status == "unknown":
                # Figure out who this used to belong to before wiping it
                old_subject_id = str(linked_embedding.to_dict().get("subject_id") or "").strip().lower()

                if old_subject_id:
                    # Forget this known person globally for this device
                    all_person_embeddings = (
                        database.collection("embeddings")
                        .where("user_id", "==", user_id)
                        .where("subject_id", "==", old_subject_id)
                        .stream()
                    )

                    count = 0
                    for emb_doc in all_person_embeddings:
                        emb_doc.reference.update({
                            "subject_id": "",
                            "status": "unknown",
                        })
                        count += 1

                    logging.info(
                        f"Cleared {count} embeddings for subject_id '{old_subject_id}' on user '{user_id}'"
                    )
                else:
                    # Fallback: at least clear the linked embedding
                    linked_embedding.reference.update({
                        "subject_id": "",
                        "status": "unknown",
                    })
                    logging.info(f"Embedding {linked_embedding.id} cleared: subject_id -> ''")

        except Exception as e:
            logging.exception(f"Error updating embedding(s) for face {doc.id}: {e}")


class GetEmbedding(Resource): # Admin Resource

    # Retrieves a specific facial embedding
    def get(self):
        """
        Retrieves a specific facial embedding
        
        Args: Embedding ID

        Returns: Embedding Object.
        """
        database = current_app.config['FIRESTORE_DB']
        embedding_id = request.args.get('embedding_id')

        # Error handling for missing fields
        if (embedding_id is None):
            return {"error": "No embedding ID provided"}, 400


        try:
            embedding_doc = database.collection('embeddings').document(embedding_id).get()

            if not embedding_doc.exists:
                return {"error": "Embedding not found"}, 404
        except Exception as e:
            logging.exception("Error retrieving embedding from collection")
            return {"error": "GetEmbedding/get : "+str(e)}, 500
        
        embedding_dict = embedding_doc.to_dict() # Convert the Firestore document to a dictionary
        
        return {"embedding": embedding_dict}, 200

class PostEmbedding(Resource): # Admin Resource
    
    # Creates a new facial embedding
    def post(self):
        """
        Creates a new facial embedding
        
        Args: User ID, Subject ID, and Embedding Data

        Returns: New Embedding ID.
        """
        database = current_app.config['FIRESTORE_DB']
        data=request.get_json()
        user_id = data.get('user_id')
        event_id = data.get('event_id')
        subject_id = data.get('subject_id')
        model_name = data.get('model_name') or DEFAULT_MODEL
        embedding_data = data.get('embedding_data')
        status = str(data.get('status') or '').strip().lower()
        if status not in ['known', 'unknown']:
            status = 'known' if str(subject_id or '').strip() else 'unknown'

        # Error handling for missing fields and invalid model names
        if user_id is None:
            return {"error": "No user ID provided"}, 400
        elif event_id is None:
            return {"error": "No event ID provided"}, 400
        elif model_name not in ALLOWED_MODELS["facial_recognition"]:
            return {"error": "Invalid model name. Allowed model names are: "+str(ALLOWED_MODELS["facial_recognition"])}, 400
        elif embedding_data is None:
            return {"error": "No embedding data provided"}, 400

        try:
            embedding_data = [float(x) for x in json.loads(embedding_data)] # Convert the embedding data to a list of floats to allow for Firestore serialization
        except Exception as e:
            logging.exception("Error parsing embedding data from a string to a list of floats for Firestore serialization")
            return {"error": "PostEmbedding/post : "+str(e)}, 400

        # Create ID for new embedding
        embedding_id = str(uuid.uuid4())

        # Embedding Object (Dictionary)
        embedding = {
            "model_name": model_name,
            "user_id": user_id,
            "event_id": event_id,
            "subject_id": subject_id,
            "status": status,
            "date_created": datetime.now(timezone.utc).isoformat(),
            "data": embedding_data,
        }

        try:
            database.collection('embeddings').document(embedding_id).set(embedding) # Store the new embedding in Firestore
        except Exception as e:
            logging.exception("Error uploading embedding to Firestore")
            return {"error": "PostEmbedding/post : "+str(e)}, 500
        
        return {"embedding_id":embedding_id}, 200

class UpdateEmbedding(Resource): # Admin Resource

    # Updates a pre-existing Face Embedding in the embedding database
    def patch(self):
        """
        Updates a pre-existing Face Embedding in the embedding database.
        
        Args: Embedding ID, User ID, Subject ID, and Embedding Data

        Returns: Success Message.
        """
        # NOTE: Need to add a check to see if the incoming data 
        # is valid before inserting, ie. if it's in the embedding 
        # dict[] structure already or not.
        database = current_app.config['FIRESTORE_DB']
        data = request.get_json()
        embedding_id = data.get('embedding_id')
        field_name = data.get('field_name')
        updated_field = data.get('updated_field')

        allowed_fields = ['subject_id', 'date_created', 'data','model_name','event_id'] # Fields that are allowed to be updated
                # Error handling for missing fields and/or invalid inputs
        if (field_name not in allowed_fields):
            return {"error": "Invalid field name. Allowed fields are: "+str(allowed_fields)}, 400
        elif (embedding_id is None):
            return {"error": "No embedding ID provided"}, 400
        elif (updated_field is None):
            return {"error": "No replacement data provided to update this field"}, 400


        if (field_name == 'data'):
            try:
                updated_field = [float(x) for x in json.loads(updated_field)] # Convert the updated embedding data to a list of floats to allow for Firestore serialization
            except Exception as e:
                logging.exception("Error parsing updated embedding data from a string to a list of floats for Firestore serialization")
                return {"error": "UpdateEmbedding/patch : "+str(e)}, 400

        try:
            database.collection('embeddings').document(embedding_id).update({field_name : updated_field,})
        except Exception as e:
            logging.exception("Error updating embedding in collection")
            return {"error": "UpdateEmbedding/patch : "+str(e)}, 500
        else:
            return {"message": "Embedding details updated successfully"}, 200


class DeleteEmbedding(Resource): # Admin Resource
    
    # Deletes an embedding from the embedding database
    def delete(self):
        """
        Deletes a pre-existing Face Embedding in the embedding database.

        Args:
            Embedding ID
        
        Returns:
            Success Message.
        """
        database = current_app.config['FIRESTORE_DB']
        embedding_id = request.args.get('embedding_id')

        # Error handling for missing fields
        if (embedding_id is None):
            return {"error": "No embedding ID provided"}, 400

        try:
            embedding = database.collection('embeddings').document(embedding_id) # Retrieve the embedding document from Firestore

            if not (embedding.get()).exists:
                return {"error": "Embedding not found"}, 404
            
            embedding.delete()  # Delete embedding from Firestore

        except Exception as e:
            logging.exception("Error deleting embedding from collection")
            return {"error": "DeleteEmbedding/delete : "+str(e)}, 500
        
        return {"message": "Embedding deleted successfully"}, 200


class MakeEmbedding(Resource):
    """ 
        Args: Image
     Returns: New Embedding.
    """
    def post(self,uid):
        database = current_app.config['FIRESTORE_DB']
        user_id = request.form.get('user_id')
        event_id = request.form.get('event_id')
        subject_id = request.form.get('subject_id') or ""
        model_name = request.form.get('model_name') or DEFAULT_MODEL
        detector_backend = request.form.get('detector_backend') or DEFAULT_DETECTOR
        image_file = request.files.get('image_file')

        # Error handling for missing fields and invalid model/detector names
        if image_file is None:
            return {"error": "No image file provided"}, 400
        elif user_id is None:
            return {"error": "No user ID provided"}, 400
        elif (uid != user_id):
            return {"error": "Unauthorized: Can only make embeddings for your own account"}, 401
        elif model_name not in ALLOWED_MODELS["facial_recognition"]:
            return {"error": "Invalid model name. Allowed model names are: "+str(ALLOWED_MODELS["facial_recognition"])}, 400
        elif detector_backend not in ALLOWED_MODELS["face_detector"]:
            return {"error": "Invalid detector name. Allowed detector names are: "+str(ALLOWED_MODELS["face_detector"])}, 400

        try:
            image = Image.open(image_file.stream)
            image = numpy.asarray(image)
        except Exception as e:
            logging.exception("Error opening provided image file")
            return {"error": "MakeEmbedding/post : "+str(e)}, 400

        # Create ID for new embedding
        embedding_id = str(uuid.uuid4())

        # Embedding Object (Dictionary)
        embedding = {
            "model_name": model_name,
            "user_id": user_id,
            "event_id": event_id,
            "subject_id": subject_id,
            "status": "known" if str(subject_id).strip() else "unknown",
            "date_created": datetime.now(timezone.utc).isoformat(),
            "data": None,
        }

        try:
            #result:Dict[str, Any]
            result = DeepFace.represent(image, model_name=model_name,detector_backend=detector_backend) # Generate the embedding vector ([0] selects the first face detected in the image, if there are multiple faces detected, only the first one will be used for generating the embedding)
            # NOTE: We will need to implement the handling of multiple faces and 
            #       add some error handling (ie. no faces detected)

            if isinstance(result, list) and len(result) > 1:
                logging.warning("Multiple faces detected in the image, using the first face.")

            if isinstance(result, list) and len(result) > 0:
                obj=result[0]
                if isinstance(obj, dict):
                    embedding["data"] = [float(x) for x in obj["embedding"]] # Convert the embedding vector to a list of floats to allow for Firestore serialization
                else:
                    return {"error": "MakeEmbedding/post : Unexpected embedding result format"}, 500
            else:
                return {"error": "MakeEmbedding/post : No face detected in image"}, 400
        except Exception as e:
            logging.exception("Error generating embedding from image")
            return {"error": "MakeEmbedding/post : "+str(e)}, 500

        try:
            database.collection('embeddings').document(embedding_id).set(embedding) # Store the new embedding in Firestore
        except Exception as e:
            logging.exception("Error uploading embedding to Firestore")
            return {"error": "MakeEmbedding/post : "+str(e)}, 500
        
        return {"embedding_id":embedding_id, "embedding": embedding}, 200


class UserEmbeddings(Resource):

    # Retrieves all embeddings of a user
    def get(self, uid):
        """
        Retrieves all embeddings of a user

        Args: User ID

        Returns: All Embeddings associated with User ID.
        """
        database = current_app.config['FIRESTORE_DB']
        user_id = request.args.get('user_id')

        # Error handling for missing fields
        if(user_id is None):
            return {"error": "No user ID provided"}, 400
        elif (uid != user_id):
            return {"error": "Unauthorized: Can only get embeddings from your own account"}, 401

        try:
            embedding_docs = database.collection('embeddings').where('user_id', '==', user_id).stream()
            embedding_dicts = [embedding.to_dict() for embedding in embedding_docs] # Convert Firestore documents into a LIST of dictionaries - List[Dict[embedding fields]]
        except Exception as e:
            logging.exception("Error retrieving user's embeddings")
            return {"error": "UserEmbeddings/get : "+str(e)}, 500
        return {"embeddings": embedding_dicts}, 200

    # Deletes all embeddings associated with a given user ID
    def delete(self, uid):
        """
        Deletes all embeddings associated with a given user ID.

        Args: User ID
     
        Returns: Success Message
        """
        database = current_app.config['FIRESTORE_DB']
        user_id = request.args.get('user_id')

        # Error handling for missing fields
        if(user_id is None):
            return {"error": "No user ID provided"}, 400
        elif (uid != user_id):
            return {"error": "Unauthorized: Can only delete your own embeddings"}, 401

        try:
            embeddings = database.collection('embeddings').where('user_id', '==', user_id).stream() # Retrieve all embedding documents associated with the user ID

            for embedding in embeddings:
                embedding.reference.delete()  # Delete each embedding document

        except Exception as e:
            logging.exception("Error deleting user's embeddings")
            return {"error": "UserEmbeddings/delete : "+str(e)}, 500
        return {"message": "User's embeddings deleted successfully"}, 200


class SubjectEmbeddings(Resource):

    # Retrieves all embeddings of a subject
    def get(self, uid):
        """
        Args: User ID and Subject ID
     Returns: All Embeddings associated with a Subject ID and User ID.
        """
        database = current_app.config['FIRESTORE_DB']
        user_id = request.args.get('user_id')
        subject_id = request.args.get('subject_id')

        # Error handling for missing fields
        if(user_id is None):
            return {"error": "No user ID provided"}, 400
        elif (uid != user_id):
            return {"error": "Unauthorized: Can only get embeddings from your own account"}, 401
        elif(subject_id is None):
            return {"error": "No subject ID provided"}, 400


        try:
            embedding_docs = database.collection('embeddings').where('user_id', '==', user_id).where('subject_id', '==', subject_id).stream()
            embedding_dicts = [embedding.to_dict() for embedding in embedding_docs] # Convert Firestore documents into a LIST of dictionaries - List[Dict[embedding fields]]
        except Exception as e:
            logging.exception("Error retrieving subject's embeddings")
            return {"error": "SubjectEmbeddings/get : "+str(e)}, 500
        return {"embeddings": embedding_dicts}, 200

    # Deletes all embeddings of a specific subject (subject_id), associated with a specific user's account (user_id).
    def delete(self, uid):
        """
        Deletes all embeddings of a specific subject, associated with a given user account
        """
        database = current_app.config['FIRESTORE_DB']
        user_id = request.args.get('user_id')
        subject_id = request.args.get('subject_id')

        # Error handling for missing fields
        if(user_id is None):
            return {"error": "No user ID provided"}, 400
        elif (uid != user_id):
            return {"error": "Unauthorized: Can only delete embeddings from your own account"}, 401
        elif(subject_id is None):
            return {"error": "No subject ID provided"}, 400
        

        try:
            embeddings = database.collection('embeddings').where('user_id', '==', user_id).where('subject_id', '==', subject_id).stream() # Retrieve all embedding documents associated with the subject ID

            for embedding in embeddings:
                embedding.reference.delete()  # Delete each embedding document

        except Exception as e:
            logging.exception("Error deleting subject's embeddings")
            return {"error": "SubjectEmbeddings/delete : "+str(e)}, 500
        return {"message": "Subject's embeddings deleted successfully"}, 200




