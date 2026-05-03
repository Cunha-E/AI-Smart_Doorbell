import React, { useEffect, useMemo, useState } from "react";
import { View, Text, Pressable, Image, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { doc, onSnapshot } from "firebase/firestore";
import { getDownloadURL, ref as storageRef } from "firebase/storage";
import { db, storage } from "@/src/firebase";
import { Screen } from "@/components/ui/Screen";

type EventDoc = {
  createdAt?: any;
  type?: string;
  result?: string;
  photoPath?: string;

  // optional if you ever write it later
  personName?: string;
};

type FaceDoc = {
  status?: "known" | "unknown";
  name?: string;
};

function formatTimestamp(ts: any) {
  try {
    const d =
      ts?.toDate ? ts.toDate() :
      ts instanceof Date ? ts :
      ts ? new Date(ts) : null;

    if (!d || isNaN(d.getTime())) return "—";
    return d.toLocaleString();
  } catch {
    return "—";
  }
}

function normalizeResult(result?: string) {
  const r = (result ?? "").toLowerCase().trim();

  // handle weird values like "unknown | known" or "unknown or known"
  if (r.includes("known") && !r.includes("unknown")) return "Known";
  if (r.includes("unknown")) return "Unknown";
  if (r === "known") return "Known";
  if (r === "unknown") return "Unknown";

  return "Unknown";
}

function normalizeType(type?: string) {
  const t = (type ?? "ring").toLowerCase().trim();
  if (!t) return "ring";
  // Make it look nicer in UI
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function getPersonLabel(event: EventDoc | null, face: FaceDoc | null) {
  const faceName = (face?.name ?? "").trim();
  if (faceName.length > 0) return faceName;

  const cachedName = (event?.personName ?? "").trim();
  if (cachedName.length > 0) return cachedName;

  if (face?.status === "known") return "Known";
  if (face?.status === "unknown") return "Unknown";

  return normalizeResult(event?.result);
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ flexDirection: "row", paddingVertical: 10 }}>
      <Text style={{ width: 92, color: "#666", fontWeight: "800" }}>{label}</Text>
      <Text style={{ flex: 1, color: "#111", fontWeight: "800" }}>{value}</Text>
    </View>
  );
}

export default function EventDetailsScreen() {
  const router = useRouter();
  const { deviceId, eventId } = useLocalSearchParams<{ deviceId: string; eventId: string }>();

  const [loading, setLoading] = useState(true);
  const [event, setEvent] = useState<EventDoc | null>(null);
  const [face, setFace] = useState<FaceDoc | null>(null);
  const [err, setErr] = useState("");

  const [url, setUrl] = useState("");
  const [urlErr, setUrlErr] = useState("");

  // Load event doc
  useEffect(() => {
    if (!deviceId || !eventId) return;

    setLoading(true);
    setErr("");

    const refDoc = doc(db, "devices", String(deviceId), "events", String(eventId));

    const unsub = onSnapshot(
      refDoc,
      (snap) => {
        setEvent(snap.exists() ? ((snap.data() as any) ?? null) : null);
        setLoading(false);
      },
      (e) => {
        setErr(e.message);
        setLoading(false);
      }
    );

    return unsub;
  }, [deviceId, eventId]);

  // Load matching face doc by SAME ID (so we can show name/status)
  useEffect(() => {
    if (!deviceId || !eventId) return;

    const faceRef = doc(db, "devices", String(deviceId), "faces", String(eventId));

    const unsub = onSnapshot(
      faceRef,
      (snap) => {
        setFace(snap.exists() ? ((snap.data() as any) ?? null) : null);
      },
      () => {
        // ignore face errors; we can still show fallback from event.result
        setFace(null);
      }
    );

    return unsub;
  }, [deviceId, eventId]);

  // Load photo URL
  useEffect(() => {
    setUrl("");
    setUrlErr("");

    if (!event?.photoPath) return;

    let cancelled = false;

    (async () => {
      try {
        const u = await getDownloadURL(storageRef(storage, event.photoPath!));
        if (!cancelled) setUrl(u);
      } catch (e: any) {
        if (!cancelled) setUrlErr(e?.message ?? "photo failed");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [event?.photoPath]);

  const actionLabel = useMemo(() => normalizeType(event?.type), [event?.type]);
  const personLabel = useMemo(() => getPersonLabel(event, face), [event, face]);

  return (
    <Screen>
      <Pressable onPress={() => router.back()} style={{ marginBottom: 12 }}>
        <Text style={{ color: "#111", fontWeight: "900", fontSize: 16 }}>← Back</Text>
      </Pressable>

      {loading ? (
        <View style={{ marginTop: 16 }}>
          <ActivityIndicator />
        </View>
      ) : err ? (
        <Text style={{ marginTop: 16, color: "#b00020", fontWeight: "800" }}>{err}</Text>
      ) : !event ? (
        <Text style={{ marginTop: 16, color: "#666", fontWeight: "700" }}>Event not found.</Text>
      ) : (
        <>
          {/* Photo */}
          <View
            style={{
              width: "100%",
              height: 280,
              borderRadius: 22,
              backgroundColor: "#eee",
              overflow: "hidden",
              justifyContent: "center",
              alignItems: "center",
              borderWidth: 1,
              borderColor: "#e6e6e6",
            }}
          >
            {url ? (
              <Image source={{ uri: url }} style={{ width: "100%", height: "100%" }} resizeMode="cover" />
            ) : (
              <Text style={{ color: "#888", fontWeight: "900" }}>{urlErr ? "No photo" : "Loading…"}</Text>
            )}
          </View>

          {/* Details */}
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
            <Text style={{ fontSize: 18, fontWeight: "900", color: "#111" }}>Details</Text>

            <View style={{ marginTop: 8 }}>
              <DetailRow label="Device:" value={String(deviceId)} />
              <DetailRow label="Date:" value={formatTimestamp(event.createdAt)} />
              <DetailRow label="Action:" value={actionLabel} />
              <DetailRow label="Person:" value={personLabel} />
            </View>
          </View>
        </>
      )}
    </Screen>
  );
}
