"""
This module handles resources/logic used by the Image API.

   To-Do:
        - Implement error handling
        - Implement handling of different image classifications (unreviewed images, reviewed images, images of specific subjects, etc.)
 
   Resources:
        - Image
        - ImageBulk
        - ImageSubject
        - ImageClass
        - Images (Model)
"""

# Std Library Imports:
import logging
import uuid

# 3rd-Party Imports:
from flask import jsonify, request
from flask_restful import Resource
from firebase_admin import storage
from PIL import Image as PILImage
from PIL import ExifTags

# Local Imports:
from source.app import get_db

# Deals with individual Images
class Image(Resource):

    # Retrieves a specific image
    def get(self, uid):
        """
        Returns a single image for a given image ID.
        """
        database = get_db()
        req = request.get_json()
        img_id = request.headers.get('img_id')
        user_id = request.headers.get('user_id')

        if (uid != user_id):
            return {"error": "Unauthorized: Can only get photos from your own account"}, 401

        try:
            image_meta = database.collection('images').document(img_id).get()

            if not image_meta.exists:
                return {"error": "Image not found"}, 404
            
            image_meta = image_meta.to_dict() # Convert the Firestore document to a dictionary

            if(image_meta['user_id'] != user_id):
                return {"error": "Unauthorized: This photo does not belong to your account"}, 401

        except Exception as e:
            logging.exception("Error retrieving image metadata")
            return {"error": "Image/get : "+str(e)}, 500
        
        bucket = storage.bucket() # Access the Firebase Storage bucket
        blob = bucket.blob(image_meta['image_path']) # Create a blob object using the internal storage path
        temp_url = blob.generate_signed_url(version="v4", expiration=120) # Signed URL valid for 2 minutes
        
        try:
            image = image_meta
            image['temp_url'] = temp_url # Adds the temporary URL to the image dictionary
            image.pop('image_path', None) # Removing the internal path
            return {"image":image}, 200
        except Exception as e:
            logging.exception("Error downloading image data")
            return {"error": "Image/get : "+str(e)}, 500

    # Inserts a new image into the image database
    def post(self,uid):
        """
        Inserts a new image into the image database, given the user ID, device number, and image data.
        """
        database = get_db()
        user_id = request.form.get('user_id')
        device_id = request.form.get('device_id')
        image_data = request.files.get('image_data')
        
        if (uid != user_id):
            return {"error": "Unauthorized: Can only add photos for your own account"}, 401

        
        bucket = storage.bucket() # Access the Firebase Storage bucket
        img_id = str(uuid.uuid4()) # Generate a unique image ID
        image_path = f'image_bucket/{img_id}' # Define the internal storage path
        blob = bucket.blob(image_path) # Create a blob object using the internal storage path

        try:
            blob.upload_from_file(image_data) # Upload the image data to Firebase Storage
            image_data.seek(0) # Reset the file pointer (after uploading the pointer is at EOF)
            image_meta = create_metadata(image_data, user_id, device_id,image_path) # Create the metadata for the image
            database.collection('images').document(img_id).set(image_meta) # Store the metadata in Firestore with the image ID as the document ID
            return {"message": "Image uploaded successfully", "img_id": img_id}, 201
        except Exception as e:
            logging.exception("Error uploading image")
            return {"error": "Image/post : "+str(e)}, 500
        
    # Update an image's metadata
    def patch(self,uid):
        """
        Updates an images metadata in the database.
        """
        database = get_db()
        img_id = request.form.get('img_id')
        user_id = request.form.get('user_id',)
        field_name = request.form.get('field_name')
        updated_field = request.form.get('updated_field')

        if (uid != user_id):
            return {"error": "Unauthorized: Can only update the metadata of your own photos"}, 401

        try:
            database.collection('images').document(img_id).update({field_name : updated_field,})
        except Exception as e:
            logging.exception("Error updating image metadata")
            return {"error": "Image/patch : "+str(e)}, 500
        else:
            return {"message": "Image details updated successfully"}, 200

    # Deletes an image from the image database
    def delete(self,uid):
        """
        Deletes an image, given an image ID is provided.
        """
        database = get_db()
        img_id = request.headers.get('img_id')
        user_id = request.headers.get('user_id')

        if (uid != user_id):
            return {"error": "Unauthorized: Can only add photos for your own account"}, 401

        # Step 1: Retrieve the image metadata from Firestore using the provided image ID to get the internal storage path
        try:
            image_meta = database.collection('images').document(img_id).get()

            if not image_meta.exists:
                return {"error": "Image not found"}, 404
            
            image_meta = image_meta.to_dict() # Convert the Firestore document to a dictionary

            if(image_meta['user_id'] != user_id):
                return {"error": "Unauthorized: This photo does not belong to your account"}, 401
        except Exception as e:
            logging.exception("Error retrieving image metadata")
            return {"error": "Image/delete : "+str(e)}, 500

        # Step 2: Access Firebase Storage and Create a Blob Object
        bucket = storage.bucket()
        blob = bucket.blob(image_meta['image_path']) # Create a blob object using the internal storage path

        # Step 3: Delete the image file from Firebase Storage
        try:
            blob.delete() # Delete the image from Firebase Storage
        except Exception as e:
            logging.exception("Error deleting image")
            return {"error": "Image/delete : "+str(e)}, 500
        
        # Step 4: Delete the image metadata from Firestore Collections
        try:
            database.collection('images').document(img_id).delete() # Delete the image metadata from Firestore
        except Exception as e:
            logging.exception("Error deleting image")
            return {"error": "Image/delete : "+str(e)}, 500
        
        return {"message": "Image deleted successfully"}, 200

# Deals with a User's Images in bulk
class ImageBulk(Resource):
    # Retrieves ALL of a user's images
    def get(self,uid):
        """
        Returns all images for a given user ID.
        """
        database = get_db()
        user_id = request.headers.get('user_id')
        images = [] # The final list of image metadata dictionaries that will be returned in the response

        if (uid != user_id):
            return {"error": "Unauthorized: Can only get photos from your own account"}, 401

        try:
            image_docs = database.collection('images').where('user_id', '==', user_id).stream()
            image_dicts = [image.to_dict() for image in image_docs] # Convert Firestore documents into a LIST of dictionaries - List[Dict[image metadata fields]]
        except Exception as e:
            logging.exception("Error retrieving bulk image metadata")
            return {"error": "ImageBulk/get : "+str(e)}, 500
        
        bucket = storage.bucket() # Access the image storage bucket
        for image in image_dicts:
            try:
                blob = bucket.blob(image['image_path']) # Create a blob object using the internal storage path
                temp_url = blob.generate_signed_url(version="v4", expiration=120) # Signed URL valid for 2 minutes
                image['temp_url'] = temp_url # Adds the temporary URL to the image dictionary
                image.pop('image_path', None) # Removing the internal path
                images.append(image) # Add the image metadata dictionary (with the temporary URL) to the list of images to be returned
            except Exception as e:
                logging.exception("Error while replacing the storage paths with temporary URLs")
                return {"error": "ImageBulk/get : "+str(e)}, 500


        return {"images": images}, 200

    # Deletes all of a User's images from the image database
    def delete(self,uid):
        """
        Deletes an image, given a user ID is provided.
        """
        database = get_db()
        user_id = request.headers.get('user_id')

        if (uid != user_id):
            return {"error": "Unauthorized: Can only delete photos from your own account"}, 401

        # Step 1: Retrieve all of the user's image metadata from Firestore
        try:
            image_docs = database.collection('images').where('user_id', '==', user_id).stream()
            image_dicts = [image.to_dict() for image in image_docs]

            if not image_docs.exists:
                return {"error": "Images not found"}, 404

        except Exception as e:
            logging.exception("Error retrieving bulk image metadata")
            return {"error": "ImageBulk/delete : "+str(e)}, 500
    
        # Step 2: Access Firebase Storage
        bucket = storage.bucket()

        # Step 3: Delete the image files from Firebase Storage and the image metadata from Firestore Collections
        try:

            for image in image_dicts: # Iterate through each image metadata dictionary in the list

                # Step 3.1: Delete the image file from Firebase Storage
                try:
                    blob = bucket.blob(image['image_path']) # Create a blob object using the internal storage path
                    blob.delete() # Delete the image from Firebase Storage
                except Exception as e:
                    logging.exception("Error deleting image file")
                    return {"error": "ImageBulk/delete : "+str(e)}, 500
                
                # Step 3.2: Delete the image metadata from Firestore Collections
                try:
                    database.collection('images').document(image['img_id']).delete() # Delete the image metadata from Firestore
                except Exception as e:
                    logging.exception("Error deleting image metadata")
                    return {"error": "ImageBulk/delete : "+str(e)}, 500
        except Exception as e:
            logging.exception("Error while deleting the user's images")
            return {"error": "ImageBulk/delete : "+str(e)}, 500

        return {"message": "All of the user's images were deleted successfully"}, 200

# Deals with a Subject's Images in bulk
class ImageSubject(Resource):
    # Retrieves ALL of a subject's images
    def get(self,uid):
        """
        Returns all images for a given subject ID.
        """
        database = get_db()
        user_id = request.headers.get('user_id')
        subject_id = request.headers.get('subject_id')
        images = [] # The final list of image metadata dictionaries that will be returned in the response

        if (uid != user_id):
            return {"error": "Unauthorized: Can only get photos from your own account"}, 401

        try:
            image_docs = database.collection('images').where('user_id', '==', user_id).where('subjects', 'array-contains', subject_id).stream()
            image_dicts = [image.to_dict() for image in image_docs] # Convert Firestore documents into a LIST of dictionaries - List[Dict[image metadata fields]]
        except Exception as e:
            logging.exception("Error retrieving subject's bulk image metadata")
            return {"error": "ImageSubject/get : "+str(e)}, 500
        
        bucket = storage.bucket() # Access the image storage bucket
        for image in image_dicts:
            try:
                blob = bucket.blob(image['image_path']) # Create a blob object using the internal storage path
                temp_url = blob.generate_signed_url(version="v4", expiration=120) # Signed URL valid for 2 minutes
                image['temp_url'] = temp_url # Adds the temporary URL to the image dictionary
                image.pop('image_path', None) # Removing the internal path
                images.append(image) # Add the image metadata dictionary (with the temporary URL) to the list of images to be returned
            except Exception as e:
                logging.exception("Error while replacing the storage paths with temporary URLs")
                return {"error": "ImageSubject/get : "+str(e)}, 500


        return {"images": images}, 200

    # Deletes all of a subject's images from the image database
    def delete(self, uid):
        """
        Deletes an image, given a subject ID is provided.
        """
        database = get_db()
        req = request.get_json()
        user_id = req['user_id']
        subject_id = req['subject_id']

        
        if (uid != user_id):
            return {"error": "Unauthorized: Can only delete photos from your own account"}, 401

        # Step 1: Retrieve all of the user's image metadata from Firestore
        try:
            image_docs = database.collection('images').where('user_id', '==', user_id).where('subjects', 'array-contains', subject_id).stream()
            image_dicts = [image.to_dict() for image in image_docs]

            if not image_docs.exists:
                return {"error": "Images not found"}, 404

        except Exception as e:
            logging.exception("Error retrieving subject's bulk image metadata")
            return {"error": "ImageSubject/delete : "+str(e)}, 500
    
        # Step 2: Access Firebase Storage
        bucket = storage.bucket()

        # Step 3: Delete the image files from Firebase Storage and the image metadata from Firestore Collections
        try:

            for image in image_dicts: # Iterate through each image metadata dictionary in the list

                # Step 3.1: Delete the image file from Firebase Storage
                try:
                    blob = bucket.blob(image['image_path']) # Create a blob object using the internal storage path
                    blob.delete() # Delete the image from Firebase Storage
                except Exception as e:
                    logging.exception("Error deleting image file")
                    return {"error": "ImageSubject/delete : "+str(e)}, 500
                
                # Step 3.2: Delete the image metadata from Firestore Collections
                try:
                    database.collection('images').document(image['img_id']).delete() # Delete the image metadata from Firestore
                except Exception as e:
                    logging.exception("Error deleting image metadata")
                    return {"error": "ImageSubject/delete : "+str(e)}, 500
        except Exception as e:
            logging.exception("Error while deleting the images of this subject")
            return {"error": "ImageSubject/delete : "+str(e)}, 500

        return {"message": "All of the subject's images were deleted successfully"}, 200

# Deals with a Class of Images in bulk
class ImageClass(Resource):
    # Retrieves ALL of a user's images. of a specified classification
    def get(self,uid):
        """
        Returns all images for a given user ID.
        """
        database = get_db()
        user_id = request.headers.get('user_id')
        class_name = request.headers.get('class_name')
        images = [] # The final list of image metadata dictionaries that will be returned in the response

        if (uid != user_id):
            return {"error": "Unauthorized: Can only get photos from your own account"}, 401

        try:
            image_docs = database.collection('images').where('user_id', '==', user_id).where('classification', '==', class_name).stream()
            image_dicts = [image.to_dict() for image in image_docs] # Convert Firestore documents into a LIST of dictionaries - List[Dict[image metadata fields]]
        except Exception as e:
            logging.exception("Error retrieving classification's bulk image metadata")
            return {"error": "ImageClass/get : "+str(e)}, 500
        
        bucket = storage.bucket() # Access the image storage bucket
        for image in image_dicts:
            try:
                blob = bucket.blob(image['image_path']) # Create a blob object using the internal storage path
                temp_url = blob.generate_signed_url(version="v4", expiration=120) # Signed URL valid for 2 minutes
                image['temp_url'] = temp_url # Adds the temporary URL to the image dictionary
                image.pop('image_path', None) # Removing the internal path
                images.append(image) # Add the image metadata dictionary (with the temporary URL) to the list of images to be returned
            except Exception as e:
                logging.exception("Error while replacing the storage paths with temporary URLs")
                return {"error": "ImageClass/get : "+str(e)}, 500


        return {"images": images}, 200
        

def extract_metadata(image):
    """
    Extracts metadata from an image file, such as capture time and device information.
    
    :param image: Image file object
    :return: Dictionary containing extracted metadata
    """
    metadata = {}
    try:
        img = PILImage.open(image)
        exif_data = img._getexif()
        if exif_data:
            for tag, value in exif_data.items():
                decoded_tag = ExifTags.TAGS.get(tag, tag)
                metadata[decoded_tag] = value
    except Exception as e:
        logging.exception("Error extracting metadata from image")
    return metadata

def create_metadata(image, user_id, device_id, image_path):
    """
    Creates a metadata dictionary for an image, including user ID, device ID, capture time, and other relevant information.
    
    :param image: Image file object
    :param user_id: ID of the user who captured the image
    :param device_id: ID of the device that captured the image
    :param image_path: Internal storage path of the image in Firebase Storage
    :return: Dictionary containing the image metadata
    """
    metadata = extract_metadata(image)

    image_meta = {
            'archive': False, # Default to not archived
            'capture_time': metadata.get('DateTimeOriginal') or metadata.get('DateTime', None), # Use 'DateTimeOriginal' if it exists, otherwise use 'DateTime'
            'classification': "", # Placeholder for the image classification
            'from_mobile': False, # Default to not from mobile
            'subjects': [], # Placeholder for the list of subjects
            'user_id': user_id,
            'device_id': device_id,
            'image_path': image_path # Placeholder for the image's internal storage path in Firebase Storage
    }
    
    return image_meta

