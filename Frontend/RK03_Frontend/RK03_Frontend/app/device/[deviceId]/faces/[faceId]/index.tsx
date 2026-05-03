import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  Pressable,
  ActivityIndicator,
  Image,
  TextInput,
  Alert,
  ScrollView,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import {
  doc,
  onSnapshot,
  updateDoc,
  serverTimestamp,
  collection,
  query,
  where,
  getDocs,
  writeBatch,
} from "firebase/firestore";
import {
  getDownloadURL,
  ref as storageRef,
  deleteObject,
} from "firebase/storage";
import { db, storage } from "@/src/firebase";
import { Screen } from "@/components/ui/Screen";

type FaceDoc = {
  id: string;
  status?: "known" | "unknown";
  name?: string;
  photoPath?: string;
  createdAt?: any;
  updatedAt?: any;
};

function normalizePersonName(value: string) {
  return value.trim().toLowerCase();
}

export default function FaceDetailsScreen() {
  const router = useRouter();
  const { deviceId, faceId } = useLocalSearchParams<{ deviceId: string; faceId: string }>();

  const [loading, setLoading] = useState(true);
  const [face, setFace] = useState<FaceDoc | null>(null);
  const [err, setErr] = useState("");

  const [photoUrl, setPhotoUrl] = useState("");
  const [photoErr, setPhotoErr] = useState("");

  const [nameInput, setNameInput] = useState("");

  useEffect(() => {
    if (!deviceId || !faceId) return;

    setLoading(true);
    setErr("");

    const faceRef = doc(db, "devices", String(deviceId), "faces", String(faceId));

    const unsub = onSnapshot(
      faceRef,
      (snap) => {
        if (!snap.exists()) {
          setFace(null);
          setNameInput("");
          setLoading(false);
          return;
        }

        const data = { id: snap.id, ...(snap.data() as any) } as FaceDoc;
        setFace(data);
        setNameInput(data.name ?? "");
        setLoading(false);
      },
      (e) => {
        setErr(e.message);
        setLoading(false);
      }
    );

    return unsub;
  }, [deviceId, faceId]);

  useEffect(() => {
    setPhotoUrl("");
    setPhotoErr("");

    const path = face?.photoPath;
    if (!path) return;

    let cancelled = false;

    (async () => {
      try {
        const u = await getDownloadURL(storageRef(storage, path));
        if (!cancelled) setPhotoUrl(u);
      } catch (e: any) {
        console.log("PHOTO ERROR:", e?.code, e?.message);
        if (!cancelled) setPhotoErr(`${e?.code ?? "error"}: ${e?.message ?? "photo failed"}`);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [face?.photoPath]);

  async function syncEvent(result: "known" | "unknown", personName: string) {
    if (!deviceId || !faceId) return;

    const eventRef = doc(db, "devices", String(deviceId), "events", String(faceId));
    try {
      await updateDoc(eventRef, {
        result,
        personName,
        updatedAt: serverTimestamp(),
      });
    } catch {
      // ignore if event doc doesn't exist or rules block it
    }
  }

  async function saveLabel() {
    if (!deviceId || !faceId) return;

    const clean = nameInput.trim();
    const normalized = normalizePersonName(clean);
    const faceRef = doc(db, "devices", String(deviceId), "faces", String(faceId));

    try {
      if (clean.length === 0) {
        setNameInput("");

        await updateDoc(faceRef, {
          status: "unknown",
          name: "",
          updatedAt: serverTimestamp(),
        });

        await syncEvent("unknown", "");
        return;
      }

      // Check if another known face on this device already has this exact name
      const facesRef = collection(db, "devices", String(deviceId), "faces");
      const knownFacesQ = query(facesRef, where("status", "==", "known"));
      const knownFacesSnap = await getDocs(knownFacesQ);

      let duplicateFound = false;

      knownFacesSnap.forEach((snap) => {
        if (snap.id === String(faceId)) return;

        const data = snap.data() as any;
        const existingName = normalizePersonName(String(data?.name ?? ""));

        if (existingName && existingName === normalized) {
          duplicateFound = true;
        }
      });

      if (duplicateFound) {
        Alert.alert(
          "Someone already has that exact name",
          "Try adding a last name, nickname, or initial."
        );
        return;
      }

      setNameInput(clean);

      await updateDoc(faceRef, {
        status: "known",
        name: clean,
        updatedAt: serverTimestamp(),
      });

      await syncEvent("known", clean);
    } catch (e: any) {
      Alert.alert("Save failed", e?.message ?? "Unknown error");
    }
  }

  async function markUnknown() {
    if (!deviceId || !faceId || !face) return;

    const device = String(deviceId);
    const currentFaceId = String(faceId);
    const cleanName = String(face.name ?? "").trim();
    const normalizedName = cleanName.toLowerCase();

    try {
      setNameInput("");

      if (face.status === "known" && normalizedName) {
        const facesRef = collection(db, "devices", device, "faces");
        const knownFacesQ = query(facesRef, where("status", "==", "known"));
        const knownFacesSnap = await getDocs(knownFacesQ);

        const batch = writeBatch(db);

        knownFacesSnap.forEach((snap) => {
          const data = snap.data() as any;
          const snapName = String(data?.name ?? "").trim().toLowerCase();

          if (snapName === normalizedName) {
            batch.update(snap.ref, {
              status: "unknown",
              name: "",
              updatedAt: serverTimestamp(),
            });
          }
        });

        await batch.commit();
      } else {
        const faceRef = doc(db, "devices", device, "faces", currentFaceId);

        await updateDoc(faceRef, {
          status: "unknown",
          name: "",
          updatedAt: serverTimestamp(),
        });
      }

      await syncEvent("unknown", "");
    } catch (e: any) {
      Alert.alert("Update failed", e?.message ?? "Unknown error");
    }
  }

  async function deleteStoragePaths(paths: string[]) {
    const uniquePaths = Array.from(new Set(paths.filter(Boolean)));

    for (const path of uniquePaths) {
      try {
        await deleteObject(storageRef(storage, path));
      } catch (e: any) {
        const code = String(e?.code ?? "");
        if (code !== "storage/object-not-found") {
          console.log("Storage cleanup skipped:", e?.message ?? e);
        }
      }
    }
  }

  async function forgetKnownPerson() {
    if (!deviceId || !face) return;

    const device = String(deviceId);
    const cleanName = String(face.name ?? "").trim();
    const normalizedName = cleanName.toLowerCase();

    if (!cleanName) {
      Alert.alert("Delete failed", "This known person does not have a valid name.");
      return;
    }

    try {
      const batch = writeBatch(db);
      const storagePaths: string[] = [];

      // Delete all KNOWN face docs for this person on this device
      const facesRef = collection(db, "devices", device, "faces");
      const knownFacesQ = query(facesRef, where("status", "==", "known"));
      const knownFacesSnap = await getDocs(knownFacesQ);

      knownFacesSnap.forEach((snap) => {
        const data = snap.data() as any;
        const snapName = String(data?.name ?? "").trim().toLowerCase();

        if (snapName === normalizedName) {
          batch.delete(snap.ref);

          const path =
            typeof data?.photoPath === "string" && data.photoPath.trim().length > 0
              ? data.photoPath.trim()
              : `devices/${device}/faces/${snap.id}.jpg`;

          storagePaths.push(path);
        }
      });

      // Delete all embeddings used to recognize this known person in the future
      const embeddingsRef = collection(db, "embeddings");
      const embeddingsQ = query(embeddingsRef, where("user_id", "==", device));
      const embeddingsSnap = await getDocs(embeddingsQ);

      embeddingsSnap.forEach((snap) => {
        const data = snap.data() as any;
        const subjectId = String(data?.subject_id ?? "").trim().toLowerCase();

        if (subjectId === normalizedName) {
          batch.delete(snap.ref);
        }
      });

      await batch.commit();
      await deleteStoragePaths(storagePaths);

      router.back();
    } catch (e: any) {
      Alert.alert("Delete failed", e?.message ?? "Unknown error");
    }
  }

  async function deleteSingleUnknownFace() {
    if (!deviceId || !faceId) return;

    const device = String(deviceId);
    const faceDocId = String(faceId);

    try {
      const batch = writeBatch(db);
      const storagePaths: string[] = [];

      const faceRef = doc(db, "devices", device, "faces", faceDocId);
      batch.delete(faceRef);

      const path =
        face?.photoPath?.trim() ||
        `devices/${device}/faces/${faceDocId}.jpg`;

      storagePaths.push(path);

      const embeddingsRef = collection(db, "embeddings");
      const embeddingsQ = query(embeddingsRef, where("user_id", "==", device));
      const embeddingsSnap = await getDocs(embeddingsQ);

      embeddingsSnap.forEach((snap) => {
        const data = snap.data() as any;
        const eventId = String(data?.event_id ?? "").trim();

        if (eventId === faceDocId) {
          batch.delete(snap.ref);
        }
      });

      await batch.commit();
      await deleteStoragePaths(storagePaths);

      router.back();
    } catch (e: any) {
      Alert.alert("Delete failed", e?.message ?? "Unknown error");
    }
  }

  async function deleteFaceDoc() {
    if (!deviceId || !faceId || !face) return;

    const isKnownPerson =
      face.status === "known" && String(face.name ?? "").trim().length > 0;

    if (isKnownPerson) {
      const cleanName = String(face.name ?? "").trim();

      Alert.alert(
        "Forget this person?",
        `This will remove ${cleanName} from your Known folder and delete their saved recognition embeddings. Past notifications will stay the same, but future detections will become unknown until you label them again.`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Delete",
            style: "destructive",
            onPress: forgetKnownPerson,
          },
        ]
      );
      return;
    }

    Alert.alert(
      "Delete face?",
      "This will delete this face document, its saved image, and its matching embedding.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: deleteSingleUnknownFace,
        },
      ]
    );
  }

  return (
    <Screen>
      <ScrollView showsVerticalScrollIndicator={false}>
        <Pressable onPress={() => router.back()} style={{ marginBottom: 12 }}>
          <Text style={{ color: "#111", fontWeight: "900", fontSize: 16 }}>← Back</Text>
        </Pressable>

        {loading ? (
          <View style={{ marginTop: 16 }}>
            <ActivityIndicator />
          </View>
        ) : err ? (
          <Text style={{ marginTop: 16, color: "#b00020", fontWeight: "800" }}>{err}</Text>
        ) : !face ? (
          <Text style={{ marginTop: 16, color: "#666", fontWeight: "700" }}>Person not found.</Text>
        ) : (
          <>
            <Text style={{ fontSize: 34, fontWeight: "900", color: "#111" }}>
              {face.status === "known" ? (face.name?.trim() ? face.name : "Known Person") : "Unknown Person"}
            </Text>

            <View
              style={{
                marginTop: 14,
                borderWidth: 1,
                borderColor: "#e6e6e6",
                borderRadius: 22,
                padding: 14,
                backgroundColor: "#fff",
              }}
            >
              <View
                style={{
                  width: "100%",
                  height: 280,
                  borderRadius: 18,
                  backgroundColor: "#eee",
                  overflow: "hidden",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {photoUrl ? (
                  <Image source={{ uri: photoUrl }} style={{ width: "100%", height: "100%" }} resizeMode="cover" />
                ) : (
                  <Text style={{ color: "#888", fontWeight: "900" }}>
                    {photoErr ? "No photo" : "Loading…"}
                  </Text>
                )}
              </View>

              {!!photoErr && (
                <Text style={{ marginTop: 10, color: "#b00020", fontWeight: "800" }}>
                  {photoErr}
                </Text>
              )}

              <Text style={{ marginTop: 12, color: "#666", fontWeight: "800" }}>
                Status: {face.status ?? "unknown"}
              </Text>
            </View>

            <View
              style={{
                marginTop: 16,
                borderWidth: 1,
                borderColor: "#e6e6e6",
                borderRadius: 22,
                padding: 16,
                backgroundColor: "#fff",
              }}
            >
              <Text style={{ fontWeight: "900", color: "#111", fontSize: 18 }}>Label</Text>

              <TextInput
                value={nameInput}
                onChangeText={setNameInput}
                placeholder="Type a name (e.g. Erik)"
                autoCapitalize="words"
                style={{
                  marginTop: 12,
                  borderWidth: 1,
                  borderColor: "#ddd",
                  borderRadius: 14,
                  padding: 12,
                  fontWeight: "700",
                }}
              />

              <Pressable
                onPress={saveLabel}
                style={({ pressed }) => ({
                  marginTop: 12,
                  backgroundColor: "#111",
                  padding: 12,
                  borderRadius: 14,
                  alignItems: "center",
                  opacity: pressed ? 0.7 : 1,
                })}
              >
                <Text style={{ color: "#fff", fontWeight: "900" }}>Save</Text>
              </Pressable>

              <Pressable
                onPress={markUnknown}
                style={({ pressed }) => ({
                  marginTop: 10,
                  borderWidth: 1,
                  borderColor: "#e5e5e5",
                  padding: 12,
                  borderRadius: 14,
                  alignItems: "center",
                  opacity: pressed ? 0.7 : 1,
                })}
              >
                <Text style={{ color: "#111", fontWeight: "900" }}>Mark as Unknown</Text>
              </Pressable>

              <Pressable
                onPress={deleteFaceDoc}
                style={({ pressed }) => ({
                  marginTop: 10,
                  borderWidth: 1,
                  borderColor: "#ffcccc",
                  padding: 12,
                  borderRadius: 14,
                  alignItems: "center",
                  opacity: pressed ? 0.7 : 1,
                })}
              >
                <Text style={{ color: "#b00020", fontWeight: "900" }}>Delete</Text>
              </Pressable>
            </View>
          </>
        )}
      </ScrollView>
    </Screen>
  );
}