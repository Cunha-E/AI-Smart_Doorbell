# device_api/firebase_init.py
import os
import firebase_admin
from firebase_admin import credentials, firestore

# Path to your service account JSON
cred_path = os.path.join(os.path.dirname(__file__),
                        "instance/firebase-service-account.json")

# Initialize Firebase app (only once)
if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)

# Firestore client
db = firestore.client()