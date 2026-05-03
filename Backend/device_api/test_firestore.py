# device_api/test_firestore.py
from firebase_init import db  # Import the Firestore client

# ex: get all devices from Firestore
devices_ref = db.collection("devices")
for doc in devices_ref.stream():
    print(doc.id, doc.to_dict())

