/*********
ESP32CAM Photo Capture + Firebase Storage + Firestore Events
*********/
#define ENABLE_USER_AUTH
#define ENABLE_STORAGE
#define ENABLE_FIRESTORE
#define ENABLE_FS

#include <Arduino.h>
#include <FirebaseClient.h>
#include <FS.h>
#include <LittleFS.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include "esp_camera.h"
#include <time.h>

#define WIFI_SSID "YOUR_WIFI_NAME"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"

#define API_KEY "YOUR_FIREBASE_API_KEY"
#define USER_EMAIL "YOUR_FIREBASE_EMAIL"
#define USER_PASSWORD "YOUR_FIREBASE_PASSWORD"
#define FIREBASE_PROJECT_ID "YOUR_FIREBASE_PROJECT_ID"

#define STORAGE_BUCKET_ID "YOUR_FIREBASE_STORAGE_BUCKET"

#define FILE_PHOTO_PATH "/photo.jpg"
#define BUCKET_FOLDER "devices/DEMO_DEVICE/events"
#define FIRESTORE_EVENTS_COLLECTION "devices/DEMO_DEVICE/events"
#define DEVICE_ID "DEMO_DEVICE"

#define AUTH_TASK_UID "authTask"
#define UPLOAD_TASK_UID "uploadTask"
#define CREATE_EVENT_TASK_UID "createEventTask"

#define BUZZER_PIN 14
#define BUTTON_PIN 13

// OV2640 camera module pins (CAMERA_MODEL_AI_THINKER)
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

void processData(AsyncResult &aResult);
void file_operation_callback(File &file, const char *filename, file_operating_mode mode);
void capturePhotoSaveLittleFS();
void initLittleFS();
void initWiFi();
void initCamera();
void createEventDocument(const String &eventId, const String &photoPathFieldValue);
String makeEventId();
void buildEventPhotoPath(const String &eventId);
String makePhotoPathFieldValue(const String &bucketPath);
String makeCreatedAtRFC3339();
void resetWorkflowState();
String extractUploadedObjectName(const String &payload);

FileConfig media_file(FILE_PHOTO_PATH, file_operation_callback);
File myFile;

UserAuth user_auth(API_KEY, USER_EMAIL, USER_PASSWORD, 3000);

FirebaseApp app;
WiFiClientSecure ssl_client;
using AsyncClient = AsyncClientClass;
AsyncClient aClient(ssl_client);
Storage storage;
Firestore::Documents Docs;

String currentEventId = "";
String currentBucketPath = "devices/front_door_001/events/photo.jpg";
String currentPhotoPathField = "devices/front_door_001/events/photo.jpg";

// persistent C buffer for upload path
char currentBucketPathBuf[160] = "devices/front_door_001/events/photo.jpg";

bool taskComplete = false;
bool takeNewPhoto = false;
bool createEventRequested = false;

void doorbellSound() {
  int notes[] = {988, 1175, 1319, 1175, 988, 784};
  int durations[] = {120, 120, 180, 120, 180, 300};

  for (int i = 0; i < 6; i++) {
    tone(BUZZER_PIN, notes[i]);
    delay(durations[i]);
    noTone(BUZZER_PIN);
    delay(40);
  }
}

void resetWorkflowState() {
  taskComplete = false;
  takeNewPhoto = false;
  createEventRequested = false;
  currentEventId = "";
  currentBucketPath = "devices/front_door_001/events/photo.jpg";
  currentPhotoPathField = "devices/front_door_001/events/photo.jpg";
  snprintf(currentBucketPathBuf, sizeof(currentBucketPathBuf), "%s", "devices/front_door_001/events/photo.jpg");
}

void capturePhotoSaveLittleFS() {
  camera_fb_t *fb = NULL;

  for (int i = 0; i < 10; i++) {
    fb = esp_camera_fb_get();
    if (fb) {
      esp_camera_fb_return(fb);
      fb = NULL;
    }
  }

  fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Camera capture failed");
    delay(1000);
    ESP.restart();
  }

  Serial.printf("Picture file name: %s\n", FILE_PHOTO_PATH);
  File file = LittleFS.open(FILE_PHOTO_PATH, FILE_WRITE);

  if (!file) {
    Serial.println("Failed to open file in writing mode");
  } else {
    file.write(fb->buf, fb->len);
    Serial.print("The picture has been saved in ");
    Serial.print(FILE_PHOTO_PATH);
    Serial.print(" - Size: ");
    Serial.print(fb->len);
    Serial.println(" bytes");
  }

  file.close();
  esp_camera_fb_return(fb);
  delay(100);
}

void initLittleFS() {
  if (!LittleFS.begin(true)) {
    Serial.println("An error has occurred while mounting LittleFS");
    ESP.restart();
  } else {
    delay(500);
    Serial.println("LittleFS mounted successfully");
  }
}

void initWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.println("Connecting to WiFi...");
  }
  Serial.println("WiFi connected");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());
}

void initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_LATEST;

  if (psramFound()) {
    config.frame_size = FRAMESIZE_UXGA;
    config.jpeg_quality = 10;
    config.fb_count = 1;
  } else {
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x\n", err);
    ESP.restart();
  }

  Serial.println("Camera init success");
}

String makeEventId() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    return String(millis());
  }

  char buf[32];
  strftime(buf, sizeof(buf), "%Y%m%d_%H%M%S", &timeinfo);
  return String(buf) + "_" + String(millis());
}

// build path into a persistent char buffer AND String
void buildEventPhotoPath(const String &eventId) {
  snprintf(
    currentBucketPathBuf,
    sizeof(currentBucketPathBuf),
    "%s/%s.jpg",
    BUCKET_FOLDER,
    eventId.c_str()
  );

  currentBucketPath = String(currentBucketPathBuf);

  Serial.print("Generated upload path: ");
  Serial.println(currentBucketPath);
  Serial.print("Last 4 chars: ");
  Serial.println(currentBucketPath.substring(currentBucketPath.length() - 4));
}

String makePhotoPathFieldValue(const String &bucketPath) {
  return bucketPath;
}

String makeCreatedAtRFC3339() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    return "1970-01-01T00:00:00Z";
  }

  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &timeinfo);
  return String(buf);
}

// extract actual uploaded object name from Firebase payload
String extractUploadedObjectName(const String &payload) {
  int keyStart = payload.indexOf("\"name\": \"");
  if (keyStart == -1) return "";

  keyStart += 9; // length of: "name": "
  int keyEnd = payload.indexOf("\"", keyStart);
  if (keyEnd == -1) return "";

  return payload.substring(keyStart, keyEnd);
}

void createEventDocument(const String &eventId, const String &photoPathFieldValue) {
  String createdAt = makeCreatedAtRFC3339();

  Values::TimestampValue createdAtV(createdAt);
  Values::StringValue photoPathV(photoPathFieldValue);
  Values::StringValue resultV("unknown or known");
  Values::StringValue typeV("ring");

  Document<Values::Value> doc("createdAt", Values::Value(createdAtV));
  doc.add("photoPath", Values::Value(photoPathV));
  doc.add("result", Values::Value(resultV));
  doc.add("type", Values::Value(typeV));

  String documentPath = String(FIRESTORE_EVENTS_COLLECTION) + "/" + eventId;

  Serial.print("Creating Firestore event document: ");
  Serial.println(documentPath);
  Serial.print("Using photoPath field: ");
  Serial.println(photoPathFieldValue);

  Docs.createDocument(
    aClient,
    Firestore::Parent(FIREBASE_PROJECT_ID),
    documentPath,
    DocumentMask(),
    doc,
    processData,
    CREATE_EVENT_TASK_UID
  );
}

void setup() {
  Serial.begin(115200);

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  initWiFi();

  configTime(0, 0, "pool.ntp.org", "time.nist.gov");

  initCamera();

  Firebase.printf("Firebase Client v%s\n", FIREBASE_CLIENT_VERSION);

  initLittleFS();

  ssl_client.setInsecure();
  ssl_client.setConnectionTimeout(4000);
  ssl_client.setHandshakeTimeout(5);

  Serial.println("Initializing app...");
  initializeApp(aClient, app, getAuth(user_auth), processData, AUTH_TASK_UID);

  app.getApp<Storage>(storage);
  app.getApp<Firestore::Documents>(Docs);

  Serial.println("Listing files in LittleFS:");
  File root = LittleFS.open("/");
  File file = root.openNextFile();
  while (file) {
    Serial.println(file.name());
    file = root.openNextFile();
  }
}

void loop() {
  app.loop();
  Docs.loop();

  if (digitalRead(BUTTON_PIN) == LOW && app.ready() && !taskComplete) {
    delay(30);
    if (digitalRead(BUTTON_PIN) == LOW) {
      Serial.println("Button pressed -> taking photo");
      takeNewPhoto = true;
    }
  }

  if (app.ready() && !taskComplete && takeNewPhoto) {
    taskComplete = true;
    takeNewPhoto = false;
    createEventRequested = false;

    capturePhotoSaveLittleFS();
    doorbellSound();

    currentEventId = makeEventId();
    buildEventPhotoPath(currentEventId);

    // default guess before upload response arrives
    currentPhotoPathField = makePhotoPathFieldValue(currentBucketPath);

    Serial.print("Event ID: ");
    Serial.println(currentEventId);

    Serial.print("Uploading to Firebase Storage path: ");
    Serial.println(currentBucketPath);

    Serial.print("Initial Firestore photoPath field: ");
    Serial.println(currentPhotoPathField);

    storage.upload(
      aClient,
      FirebaseStorage::Parent(STORAGE_BUCKET_ID, currentBucketPathBuf),
      getFile(media_file),
      "image/jpeg",
      processData,
      UPLOAD_TASK_UID
    );
  }
}

void processData(AsyncResult &aResult) {
  if (!aResult.isResult()) {
    return;
  }

  if (aResult.isEvent()) {
    Firebase.printf("Event task: %s, msg: %s, code: %d\n",
                    aResult.uid().c_str(),
                    aResult.appEvent().message().c_str(),
                    aResult.appEvent().code());
  }

  if (aResult.isDebug()) {
    Firebase.printf("Debug task: %s, msg: %s\n",
                    aResult.uid().c_str(),
                    aResult.debug().c_str());
  }

  if (aResult.isError()) {
    Firebase.printf("Error task: %s, msg: %s, code: %d\n",
                    aResult.uid().c_str(),
                    aResult.error().message().c_str(),
                    aResult.error().code());

    if (aResult.uid() == String(UPLOAD_TASK_UID) ||
        aResult.uid() == String(CREATE_EVENT_TASK_UID)) {
      Serial.println("Workflow failed. Releasing lock for next button press.");
      resetWorkflowState();
    }
    return;
  }

  if (aResult.downloadProgress()) {
    Firebase.printf("Downloaded, task: %s, %d%% (%d of %d)\n",
                    aResult.uid().c_str(),
                    aResult.downloadInfo().progress,
                    aResult.downloadInfo().downloaded,
                    aResult.downloadInfo().total);
  }

  if (aResult.uploadProgress()) {
    Firebase.printf("Uploaded, task: %s, %d%% (%d of %d)\n",
                    aResult.uid().c_str(),
                    aResult.uploadInfo().progress,
                    aResult.uploadInfo().uploaded,
                    aResult.uploadInfo().total);

    if (aResult.uploadInfo().total == aResult.uploadInfo().uploaded) {
      Firebase.printf("Upload bytes sent for task: %s\n", aResult.uid().c_str());
    }
  }

  if (aResult.available()) {
    String payload = aResult.c_str();

    Firebase.printf("Task payload [%s]: %s\n",
                    aResult.uid().c_str(),
                    payload.c_str());

    if (aResult.uid() == String(UPLOAD_TASK_UID) && !createEventRequested) {
      // overwrite Firestore photoPath with the ACTUAL uploaded object name
      String uploadedObjectName = extractUploadedObjectName(payload);
      if (uploadedObjectName.length() > 0) {
        currentPhotoPathField = uploadedObjectName;
        Serial.print("Actual uploaded object name: ");
        Serial.println(uploadedObjectName);
      } else {
        Serial.println("Could not parse uploaded object name; using generated path.");
      }

      Serial.println("Storage task fully finished. Creating Firestore event...");
      createEventRequested = true;
      createEventDocument(currentEventId, currentPhotoPathField);
      return;
    }

    if (aResult.uid() == String(CREATE_EVENT_TASK_UID) && !aResult.isError()) {
      Serial.println("Firestore event document created successfully.");
      Serial.println("System ready for next button press.");
      resetWorkflowState();
    }
  }
}

void file_operation_callback(File &file, const char *filename, file_operating_mode mode) {
  switch (mode) {
    case file_mode_open_read:
      myFile = LittleFS.open(filename, "r");
      if (!myFile || !myFile.available()) {
        Serial.println("[ERROR] Failed to open file for reading");
      }
      break;

    case file_mode_open_write:
      myFile = LittleFS.open(filename, "w");
      break;

    case file_mode_open_append:
      myFile = LittleFS.open(filename, "a");
      break;

    case file_mode_remove:
      LittleFS.remove(filename);
      break;

    default:
      break;
  }

  file = myFile;
}
