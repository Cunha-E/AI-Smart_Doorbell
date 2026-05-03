# Std Library Imports:
from __future__ import annotations
import os
import io
import json
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import NewType
import logging

# 3rd-Party Imports:
from flask import request, Flask, current_app
from flask_restful import Resource
from firebase_admin import storage
from deepface import DeepFace
import google.auth.transport.requests as google_requests
from google.oauth2 import id_token
from PIL import Image as PIL_Image
import numpy as np
from google.cloud.firestore_v1.base_document import DocumentSnapshot, BaseDocumentReference
from google.cloud.firestore_v1.watch import DocumentChange
from google.api_core.datetime_helpers import DatetimeWithNanoseconds
from google.cloud.storage import Blob, Bucket
# These are needed for image processing:
import base64
import cv2


# Local Imports:

# CONSTANTS:
MATCH_THRESHOLD = 0.68 # Threshold for embedding matches (lower is more strict, higher is more lenient) - ArcFace cosine default is 0.6816
K_INCLUSION_THRESHOLD = 0.68 # Threshold for whether a face is included in the K-matches returned by find_batched() (lower is more strict, higher is more lenient)
UPDATE_EMBEDDING_THRESHOLD = 0.5 # Threshold for whether to update an existing embedding with a new detected face (lower is more strict, higher is more lenient)
DEFAULT_DETECTOR = os.getenv("DEFAULT_DETECTOR_BACKEND", "retinaface") # Detector backend for DeepFace (retinaface is best, but can be changed for testing purposes)
DEFAULT_MODEL = os.getenv("DEFAULT_RECOGNITION_MODEL", "ArcFace") # Model used to generate embeddings (must be consistent with the model used in the Embeddings API)
MAX_THREADS = 3 # Max threads for concurrent processing of faces (2 CPU cores | 2Gb RAM on Cloud Run)

API_URLS = {
'embeddings_api': os.getenv('EMBEDDINGS_API_URL', os.getenv('EMBEDDINGS_URL', 'http://localhost:8085')),
'image_api'     : os.getenv('IMAGE_API_URL',      os.getenv('IMAGE_URL',      'http://localhost:8086')),
'model_api'     : os.getenv('MODEL_API_URL',      os.getenv('MODEL_URL',      'http://localhost:8087')),
'notification_api'  : os.getenv('NOTIFICATION_API_URL', os.getenv('NOTIFICATION_URL', 'http://localhost:8088')),
}

# CUSTOM VARIABLE TYPES
# Face = NewType('Face', list[dict[str, any]]) # A Face is represented as a dictionary containing the face's data (embedding, facial area, etc.)
# Faces = NewType('Faces', list[Face]) # A list of Faces is represented as a list of Face dictionaries




threader = ThreadPoolExecutor(max_workers=MAX_THREADS) # ThreadPoolExecutor for concurrent processing of faces
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


# Listens to Collection : devices/{device_id}/events/{event_id}
def collection_listener(snapshot:list[DocumentSnapshot], changes:list[DocumentChange], read_time:DatetimeWithNanoseconds):
        # This function watches for changes in the Events Collection
        global _listener_initialized
        
        if not _listener_initialized:
            # Skip initial snapshot — on_snapshot fires with ALL existing documents as ADDED on first call
            _listener_initialized = True
            print(f'Listener initialized, skipping {len(changes)} existing events.')
            return

        if snapshot is not None:
            for change in changes:
                if change.type.name == 'ADDED':
                    doc:DocumentSnapshot = change.document
                    print(f'New event detected: {doc.id}')
                    # Now process the new event
                    future = threader.submit(process_new_event, doc)
                    future.add_done_callback(_thread_error_callback)
        return


# Processes new events sent from collection_listener
def process_new_event(event_data: DocumentSnapshot | dict):
    # This function would contain the logic to process a new event, such as extracting the image, calling the embedding API, etc.

    #   First the event's image is extracted.
    if isinstance(event_data, DocumentSnapshot):
        parent_ref : BaseDocumentReference= event_data.reference.parent
        grandparent_ref : BaseDocumentReference = parent_ref.parent
        event_dict = event_data.to_dict()

        # Get the UserID
        user_id = grandparent_ref.id # On firestore this would be the "Device" Document ID

        # Get Image ID
        img_id = event_data.id # This is the "Event" Document ID, which is also the image filename in Firebase Storage (events folder)
        
        if not event_dict:
            print(f"Event {img_id} has no data, skipping.")
            return

        # Get the Image URL
        image_url = event_dict.get("photoPath")
        
        # Get createdAt timestamp
        created_at = event_dict.get("createdAt")


    elif isinstance(event_data, dict): # -------------------------  NOTE: This is for testing purposes, when we want to call process_new_event directly with a dict instead of a Firestore DocumentSnapshot
        user_id = event_data.get("user_id")
        image_url = event_data.get("photoPath")
        img_id = event_data.get("event_id")
        created_at = event_data.get("createdAt")

    else:
        print("Unexpected event_data type:", type(event_data))
        return
    


    print(f"Processing new event for user {user_id} with image {image_url}")
    image_np_array = image_from_storage(image_url) # Image is extracted from Firebase Storage as a NumPy array for processing

    # ----- Scan for Faces ----- #
    try:
        extracted_objects = DeepFace.extract_faces(
            image_np_array,
            detector_backend=DEFAULT_DETECTOR,
            enforce_detection=True,
        )

        if not extracted_objects or len(extracted_objects) == 0:
            print("No faces found in the image.")
            return {'message': 'No faces found in the image.'}, 200

        filtered_faces = []
        for obj in extracted_objects:
            if not isinstance(obj, dict):
                continue

            area = obj.get("facial_area") or {}
            w = int(area.get("w", 0) or 0)
            h = int(area.get("h", 0) or 0)
            confidence = float(obj.get("confidence", 0) or 0)

            if w < 60 or h < 60:
                continue
            if confidence < 0.90:
                continue

            filtered_faces.append(obj)

        extracted_objects = filtered_faces

        if not extracted_objects:
            print("No valid faces found after filtering.")
            return {'message': 'No faces found in the image.'}, 200

        print("Scan found " + str(len(extracted_objects)) + " faces in the image.")
    except Exception as e:
        msg = str(e).lower()
        print(str(e))

        if "face could not be detected" in msg or "face cannot be detected" in msg:
            return {'message': 'No faces found in the image.'}, 200

        return {'error': str(e)}, 500




    # ----- Query Embeddings_Api for User's Embeddings----- #
    #
    # NOTE: We should add error handling when we pull representations from 
    #       the Embeddings API to make sure the model_name matches, otherwise 
    #       the embeddings won't be compatible and the comparisons will be inaccurate.
    #
    try:
        print(f"Pulling existing embeddings for user {user_id} from Embeddings API...")
        url = f'{API_URLS["embeddings_api"]}/embedding/user/{user_id}'
        headers = get_service_headers(API_URLS['embeddings_api'])
        response = requests.get(url, params={'user_id': user_id}, headers=headers)
        body = response.json()
        print(body)     # Test Print
        embedding_objs = body["embeddings"]
        print(embedding_objs) # Test Print
        representations = embeddings_to_representation(embedding_objs)
    except Exception as e:
        logging.exception("Error pulling existing embeddings for user %s: %s", user_id, str(e))
        return {'error': str(e)}, 500
    

    # ----- If no existing embeddings, all faces are unknown ----- #
    if not representations:
        print("No existing embeddings for user, treating all detected faces as UNKNOWN.")
        for face_obj in (extracted_objects if not check_if_multi(extracted_objects) else [f[0] if isinstance(f, list) else f for f in extracted_objects]):
            if isinstance(face_obj, dict):
                target_face_pixels = face_obj.get("face")
            else:
                continue
            notify_user(user_id, img_id, created_at, None, image_url, "unknown")
            embedding = DeepFace.represent(target_face_pixels, enforce_detection=False, detector_backend="skip", model_name=DEFAULT_MODEL) # type: ignore
            post_embedding_call(embedding=embedding, user_id=user_id, event_id=img_id, subject_id="", status="unknown")
        return {"message": "Scan Successful"}, 200

    # ----- Batch Comparison of Faces to Embeddings ----- #
    # Batch facial recognition on the found faces against the embeddings pulled from embeddings_api
    
    matches = []
    if(check_if_multi(extracted_objects)): # Checks if the returned extracted_objects is a list of faces (multiple) or a single face, then processes accordingly
        print("Multiple faces detected, processing batch comparison...", flush=True)
        try: 
            for face in extracted_objects:
                matches.append(DeepFace.recognition.find_batched(representations=representations, source_objs=face, model_name=DEFAULT_MODEL, threshold=K_INCLUSION_THRESHOLD, k=1)) # type: ignore
        except Exception as e:
            logging.exception("Error during multi-face batch comparison")
            return {"error": "process_new_event : "+str(e)}, 500
    else:
        print("Single face detected, processing comparison...", flush=True)
        try:
            face = extracted_objects
            print(f"  find_batched inputs: {len(representations)} representations, {len(face)} source faces", flush=True)
            print(f"  Representation keys: {representations[0].keys() if representations else 'N/A'}", flush=True)
            print(f"  Source face keys: {face[0].keys() if face else 'N/A'}", flush=True) # type: ignore
            import time as _time
            _t0 = _time.monotonic()
            print(f"  Calling find_batched at {_time.strftime('%H:%M:%S')}...", flush=True)
            result = DeepFace.recognition.find_batched(representations=representations, source_objs=face, model_name=DEFAULT_MODEL, threshold=K_INCLUSION_THRESHOLD, k=1) # type: ignore
            print(f"  find_batched returned in {_time.monotonic() - _t0:.2f}s, result length: {len(result)}", flush=True)
            matches.append(result)
        except Exception as e:
            logging.exception("Error during single-face batch comparison")
            return {"error": "process_new_event : "+str(e)}, 500


    known_faces = []
    unknown_faces = []

    # ----- Process Matches ----- #
    # find_batched returns List[List[Dict]] — outer list per source face, inner list per k-match
    print(f"Processing {len(matches)} match group(s)...", flush=True)
    try:
        for match in matches:
            for i, face_matches in enumerate(match):
                print(f"  Face {i}: {len(face_matches) if face_matches else 0} match(es) from find_batched", flush=True)
                if not face_matches:
                    # No embedding matched within threshold — treat as UNKNOWN
                    print(f"  Face {i}: No matches within threshold, treating as UNKNOWN", flush=True)
                    if check_if_multi(extracted_objects):
                        tf = extracted_objects[i] if i < len(extracted_objects) else extracted_objects[0]
                        if isinstance(tf, list):
                            tf = tf[0]
                        target_face_pixels = tf.get("face") if isinstance(tf, dict) else None
                    else:
                        tf = extracted_objects[i] if i < len(extracted_objects) else extracted_objects[0]
                        target_face_pixels = tf.get("face") if isinstance(tf, dict) else None
                    notify_user(user_id, img_id, created_at, None, image_url, "unknown")
                    if target_face_pixels is not None:
                        unknown_faces.append({"target_face": target_face_pixels, "matched_face": None})
                    continue
                face = face_matches[0] if isinstance(face_matches, list) else face_matches
                target_face_pixels = None
                if(check_if_multi(extracted_objects)):
                    if i < len(extracted_objects):
                        target_face = extracted_objects[i] 
                        if isinstance(target_face, list):
                            target_face = target_face[0]
                        if isinstance(target_face, dict):
                            target_face_pixels = target_face.get("face")
                            if target_face_pixels is not None:
                                identity = str(face.get("identity") or "").strip()
                                if face["distance"] <= MATCH_THRESHOLD and identity: # If the distance between the detected face and the embedding is below the threshold, it's a match
                                    print(f"Match found for subject {face['identity']} with distance {face['distance']}")
                                    notify_user(user_id, img_id, created_at, face["identity"], image_url, "known") # Notify the user of the match via the Notification API
                                    known_faces.append({"target_face": target_face_pixels, "matched_face": face}) # Add the matched face and its corresponding embedding match data to the known_faces list
                                else:
                                    print(f"No match for this face, closest match was {face['identity']} with distance {face['distance']}")
                                    notify_user(user_id, img_id, created_at, None, image_url, "unknown") # Notify the user of the match via the Notification API
                                    unknown_faces.append({"target_face": target_face_pixels, "matched_face": face}) # Add the unmatched face and its corresponding data to the unknown_faces list

                else:
                    if i < len(extracted_objects):
                        target_face = extracted_objects[i]
                    else:
                        target_face = extracted_objects[0]
                    if isinstance(target_face, dict):
                        target_face_pixels = target_face.get("face")
                        identity = str(face.get("identity") or "").strip()
                        if face["distance"] <= MATCH_THRESHOLD and identity: # If the distance between the detected face and the embedding is below the threshold, it's a match
                            print(f"Match found for subject {face['identity']} with distance {face['distance']}")
                            notify_user(user_id, img_id, created_at, face["identity"],image_url,"known") # Notify the user of the match via the Notification API
                            known_faces.append({"target_face":target_face_pixels, "matched_face": face}) # Add the matched face and its corresponding embedding match data to the known_faces list
                        else:
                            print(f"No match for this face, closest match was {face['identity']} with distance {face['distance']}")
                            notify_user(user_id, img_id, created_at, None,image_url,"unknown") # Notify the user of the match via the Notification API
                            unknown_faces.append({"target_face":target_face_pixels, "matched_face": face}) # Add the unmatched face and its corresponding data to the unknown_faces list
                    else:
                        logging.exception("Error during target face matching: unexpected structure in extracted_objects")
                        return {"error": "process_new_event : Process Matches Error"}, 500
                if target_face_pixels is None:
                    logging.exception("Error during target face matching: could not extract face pixels from target_face")
                    return {"error": "process_new_event : Process Matches Error"}, 500
    except Exception as e:
        logging.exception("Error during processing of matches")
        return {"error": "process_new_event : "+str(e)}, 500

    print(f"Results: {len(known_faces)} known, {len(unknown_faces)} unknown faces.", flush=True)

    # ----- Process KNOWN Faces ----- #
    for face in known_faces:
        embedding = DeepFace.represent(face['target_face'], enforce_detection=False, detector_backend="skip", model_name=DEFAULT_MODEL)
        
        # NOTE:     Right now if a known face is detected we create a new 
        #       embedding for that face and send it to the Embeddings 
        #       API to be stored, however, we can enable embedding_similarity() 
        #       to instead compare the detected face's embedding with the 
        #       existing embedding and only send an update to the Embeddings 
        #       API if the similarity is below a certain threshold. This 
        #       would cut down on unnecessary duplicates in the database.

        # DISABLED CURRENTLY - SEE NOTE ABOVE
        # if embedding_similarity(embedding, face["embedding"]) < UPDATE_EMBEDDING_THRESHOLD:
        #     update_embedding_call(embedding=embedding, user_id=user_id, event_id=img_id, subject_id=face['identity'])

        post_embedding_call(embedding=embedding, user_id=user_id, event_id=img_id, subject_id=face['matched_face']['identity'], status='known')


    # ----- Process UNKNOWN Faces ----- #
    for face in unknown_faces:
        if face.get('target_face') is None:
            continue
        embedding = DeepFace.represent(face['target_face'], enforce_detection=False, detector_backend="skip", model_name=DEFAULT_MODEL)
        post_embedding_call(embedding=embedding, user_id=user_id, event_id=img_id, subject_id="", status="unknown")

    print("Event processing complete.", flush=True)
    return {"message": "Scan Successful"}, 200









# Processes a new event (image) from OnSnapshot(events_collection)
class NewEvent(Resource):

    # Processes new images from OnSnapshot(events_collection)
    def post(self,uid):

        user_id = request.args.get('user_id') 
        img_url = request.args.get('photoPath')
        img_id = request.args.get('img_id')
        if user_id is None:
            return {"error": "No user ID provided"}, 400
        elif img_url is None:
            return {"error": "No image provided"}, 400
        elif uid != user_id:
            return {"error": "Unauthorized: Can only process events from your own account"}, 401

        # Gather needed data from the http request
        data = {"user_id":user_id, "photoPath":img_url, "event_id":img_id, "createdAt": None}

        # Now process the new event
        future = threader.submit(process_new_event, data)
        future.add_done_callback(_thread_error_callback)

        return {"message": "Scan Successful"}, 200


# Compares two faces and returns similarity result -- needed for local testing, not used in production
class CompareFaces(Resource):
    def post(self):
        req = request.get_json()

        img1 = base64_to_image(req["image1"])
        img2 = base64_to_image(req["image2"])

        result = DeepFace.verify(
            img1_path=img1,
            img2_path=img2,
            detector_backend="retinaface",  # IMPORTANT
            enforce_detection=True,
            model_name="ArcFace",            # tells DeepFace which neural network is used to generate embeddings
        )

        return result, 200



# Determines the similarity between two embeddings (cosine distance: 0 = identical, 1 = opposite)
def embedding_similarity(embedding1, embedding2):
    vec1 = np.array(embedding1[0]["embedding"] if isinstance(embedding1, list) else embedding1)
    vec2 = np.array(embedding2[0]["embedding"] if isinstance(embedding2, list) else embedding2)
    dot = np.dot(vec1, vec2)
    norm = np.linalg.norm(vec1) * np.linalg.norm(vec2)
    similarity = 1 - (dot / norm) if norm != 0 else 1.0
    return similarity


# Converts a list of embedding objects (from api) to a list of (DeepFace)representations
def embeddings_to_representation(embedding_objs):
    representations = []
    for obj in embedding_objs:
        identity = str(obj.get("subject_id") or obj.get("name") or "").strip().lower()
        status = str(obj.get("status") or "").strip().lower()
        embedding_data = obj.get("data")

        if not embedding_data:
            continue
        if not identity:
            continue
        if status == "unknown":
            continue

        representations.append({
            "identity": identity,
            "embedding": embedding_data,
            "target_x": 0,
            "target_y": 0,
            "target_w": 0,
            "target_h": 0,
        })
    return representations

# Converts a list of matches (from DeepFace) into a response format
def matches_to_response(target_faces):
    response = []
    for face in target_faces:
        match = face[0]
        response.append({
            "subject": match["identity"],
            "embedding": match["distance"],
            "src_img": match["hash"],
            "threshold": match["threshold"]
        })

    return response

# Converts a base64 string to an OpenCV image
def base64_to_image(b64_string):
    header, encoded = b64_string.split(",", 1)
    img_bytes = base64.b64decode(encoded)
    np_arr = np.frombuffer(img_bytes, np.uint8)
    return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

def check_if_multi(object):
    if isinstance(object,list):
        if isinstance(object[0], list):
            return True
        elif isinstance(object[0], dict):
            return False
        else:
            raise ValueError("Unexpected list structure")
    else:
        raise ValueError("Object is not a list")

def image_from_storage(path):
    # Gets an image from Firebase Storage (events folder)
    with flask_app.app_context():
        bucket: Bucket = storage.bucket(app=flask_app.config["FIREBASE_APP"])
        blob = bucket.blob(path)
        img_bytes = blob.download_as_bytes()
        img_buffer = io.BytesIO(img_bytes)
        pillow_img = PIL_Image.open(img_buffer)
        np_array = np.array(pillow_img)
        return np_array

def notify_user(user_id, img_id, created_at, identity, image_url, status):
    # Sends a notification to the user via the Notification API
    url = f'{API_URLS["notification_api"]}/notify'
    headers = get_service_headers(API_URLS['notification_api'])

    # Convert created_at to ISO string if it's a datetime object
    if hasattr(created_at, 'isoformat'):
        created_at = created_at.isoformat()
    
    identity = identity.lower() if identity else None

    try:
        response = requests.post(
            url,
            json={
                "user_id": user_id, # The device ID in Firestore (devices/{device_id})
                "doc_id": img_id, # Used by the Notification API to link the notification to the specific event/image in Firestore (devices/{device_id}/events/{event_id})
                "createdAt": created_at, # The timestamp of the event, used for sorting notifications in the app
                "name": identity, # The subject_id from the matched embedding (None if no match)
                "photoPath": image_url, # Path to the image in Firebase Storage
                "status": status # Whether the detected face was a "KNOWN" match or "UNKNOWN" non-match
            },
            headers=headers,
            timeout=10
        )
        print("Notification API response:", response.status_code)
    except Exception as e:
        logging.warning(f"Failed to notify user {user_id}: {e}")

def post_embedding_call(user_id, event_id, subject_id="", status="unknown", embedding=None):
    # Makes a call to the Embeddings API to store pre-computed embeddings
    url = f'{API_URLS["embeddings_api"]}/embedding/post'
    headers = get_service_headers(API_URLS['embeddings_api'])

    subject_id = str(subject_id or "").lower()
    status = str(status or "unknown").lower()

    # Extract embedding vector from DeepFace.represent() result and serialize as JSON string
    embedding_data = None
    if embedding and isinstance(embedding, list) and len(embedding) > 0:
        embedding_data = json.dumps(embedding[0]["embedding"])

    try:
        response = requests.post(
            url,
            json={
                "user_id": user_id,
                "event_id": event_id,
                "subject_id": subject_id,
                "status": status,
                "model_name": DEFAULT_MODEL,
                "embedding_data": embedding_data,
            },
            headers=headers,
            timeout=10
        )
        print("Embeddings API response:", response.status_code)
    except Exception as e:
        logging.warning(f"Failed to post embedding for user {user_id}: {e}")

def update_embedding_call():
    # Makes a call to the Embeddings API to update existing embeddings for matched faces
    url = f'{API_URLS["embeddings_api"]}/embedding/update'
    headers = get_service_headers(API_URLS['embeddings_api'])
    response = requests.post(
        url,
        json={
            # This is where the updated embedding data would go, such as user_id, subject_id, new embedding vector, facial area, etc.
        },
        headers=headers
    )
    print("Embeddings API update response:", response.status_code)