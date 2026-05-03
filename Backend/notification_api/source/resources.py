"""
This module handles resources/logic used by the Notification API.

   To-Do:
 
   Resources:
        
"""

# Std Library Imports:
from datetime import datetime, timezone
import logging
import os
import uuid
import json

# 3rd-Party Imports:
from flask import request, current_app, Flask
from flask_restful import Resource
from google.cloud import firestore
from google.cloud.storage import Blob, Bucket
from google.cloud.firestore_v1 import Client
# Local Imports:

# CONSTANTS:

flask_app: Flask = None  # type: ignore  # Set by setup_listeners() in app.py

"""Creates resource class for /notify api route that recognition_api calls"""
class Notify(Resource): 
    def post(self): 
        data = request.get_json()  # Reads the JSON and stores it in data

        if not data:
            logging.exception("Error: No JSON body found")
            return {"error": "Request body is missing JSON data"}, 400
        
        #Assign fields from json to local variables
        user_id = data.get("user_id")
        doc_id = data.get("doc_id")
        created_at = data.get("createdAt")
        name = data.get("name", "")
        photo_path = data.get("photoPath")
        status = data.get("status")

        #Error Handling
        if not doc_id:
            logging.exception("Error: doc_id is missing")
            return {"error": "doc_id is required"}, 400
        
        # Normalize status to lowercase for comparison (recognition_api sends KNOWN/UNKNOWN)
        if status:
            status = status.lower()
        else:
            logging.exception("Error: status is missing")
            return {"error": "status is required"}, 400

        if status not in ["known", "unknown"]:
            logging.exception("Error: Invalid status value, must be 'known' or 'unknown'")
            return {"error": "status must be 'known' or 'unknown'"}, 400

        #For Known faces:
        if status == "known":
            if not name:
                logging.exception("Error: Known visitor events require a name")
                return {"error": "Known visitor events require a name"}, 400
            
            event_doc = build_known_event_document(name)
            save_event_to_firestore(user_id, doc_id, event_doc)

            return {
                "message": "Known visitor event created successfully",
                "doc_id": doc_id
            }, 201

        if not created_at:
            logging.exception("Error: Unknown visitor events require createdAt")
            return {"error": "Unknown visitor events require createdAt"}, 400

        if not photo_path:
            logging.exception("Error: Unknown visitor events require photoPath")
            return {"error": "Unknown visitor events require photoPath"}, 400
        
        #Find the new photo path for the faces document
        copied_photo_path = copy_unknown_photo(user_id, doc_id, photo_path)

        event_doc = build_unknown_event_document(
            created_at=parse_created_at(created_at),
            name=name,
            photo_path=copied_photo_path
        )

        save_event_to_firestore(user_id, doc_id, event_doc)

        return {
            "message": "Unknown visitor event created successfully",
            "doc_id": doc_id,
            "copiedPhotoPath": copied_photo_path
        }, 201

#Create document in the format for known faces
def build_known_event_document(name):
    return {
        "name": name,
        "status": "known",
        "updatedAt": firestore.SERVER_TIMESTAMP
    }

#Create document in the format for unknown faces
def build_unknown_event_document(created_at, name, photo_path):
    return {
        "createdAt": created_at,
        "name": name,
        "photoPath": photo_path,
        "status": "unknown",
        "updatedAt": firestore.SERVER_TIMESTAMP
    }

def save_event_to_firestore(user_id, doc_id, event_doc):
    db : Client = flask_app.config["FIRESTORE_DB"]
    path = f"devices/{user_id}/faces"
    logging.info(f"Saving event to Firestore at {path} with data: {json.dumps(event_doc, default=str)}")
    doc_ref= db.collection(path).document(doc_id)
    doc_ref.set(event_doc)

#Copies the photo from /events to /faces in firebase
def copy_unknown_photo(user_id, doc_id, photo_path):
    #Gets storage bucket from Flask (in app.py)
    bucket : Bucket = flask_app.config["STORAGE_BUCKET"]

    #Writes full path of where to pull the photo from
    source_photo_path = photo_path #Use the actual path from the request
    source_blob = bucket.blob(source_photo_path) #Actual File (Object)

    if not source_blob.exists():
        logging.exception(f"Error: Source photo does not exist: {source_photo_path}")
        raise FileNotFoundError(f"Source photo does not exist: {source_photo_path}")

    #Write the full path of where to put the photo
    destination_photo_path = f"devices/{user_id}/faces/{doc_id}.jpg"

    #Copies object to destination path
    bucket.copy_blob(source_blob, bucket, destination_photo_path)

    #Returns the path for the event document
    return destination_photo_path

#Helper function that helpes read timestamps
def parse_created_at(created_at_value):
    if not created_at_value:
        return None

    if isinstance(created_at_value, datetime):
        return created_at_value

    return datetime.fromisoformat(created_at_value.replace("Z", "+00:00"))
