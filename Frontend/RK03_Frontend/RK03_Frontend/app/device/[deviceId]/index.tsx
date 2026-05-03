import React, { useEffect, useMemo, useState } from "react";
import { View, Text, Pressable, Image, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { collection, doc, onSnapshot, orderBy, query, limit } from "firebase/firestore";
import { getDownloadURL, ref as storageRef } from "firebase/storage";
import { onAuthStateChanged, signOut } from "firebase/auth";

import { db, storage, auth } from "@/src/firebase";
import { Screen } from "@/components/ui/Screen";

type DoorEvent = {
  id: string;
  createdAt?: any;
  type?: string;
  result?: string;      // sometimes "unknown | known"
  personName?: string;  // optional cached
  photoPath?: string;
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
  if (r.includes("known") && !r.includes("unknown")) return "Known";
  if (r.includes("unknown")) return "Unknown";
  if (r === "known") return "Known";
  if (r === "unknown") return "Unknown";
  return "Unknown";
}

function getPersonLabel(ev: DoorEvent | null, face: FaceDoc | null) {
  const faceName = (face?.name ?? "").trim();
  if (faceName) return faceName;

  const cached = (ev?.personName ?? "").trim();
  if (cached) return cached;

  if (face?.status === "known") return "Known";
  if (face?.status === "unknown") return "Unknown";

  return normalizeResult(ev?.result);
}

function PersonBadge({ label }: { label: string }) {
  const isKnown = label !== "Unknown";
  return (
    <View
      style={{
        backgroundColor: isKnown ? "rgba(0,160,90,0.15)" : "rgba(255,140,0,0.15)",
        paddingHorizontal: 12,
        paddingVertical: 7,
        borderRadius: 999,
        maxWidth: 160,
      }}
    >
      <Text
        style={{
          color: isKnown ? "#00a05a" : "#ff8c00",
          fontWeight: "900",
          fontSize: 13,
        }}
        numberOfLines={1}
      >
        {label}
      </Text>
    </View>
  );
}

function ActionCard({
  title,
  subtitle,
  onPress,
}: {
  title: string;
  subtitle: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        width: "48%",
        borderWidth: 1,
        borderColor: "#e6e6e6",
        borderRadius: 22,
        paddingVertical: 18,
        paddingHorizontal: 14,
        backgroundColor: "#fff",
        opacity: pressed ? 0.75 : 1,
        alignItems: "center",
        justifyContent: "center",
        minHeight: 110,
      })}
    >
      <Text style={{ fontSize: 18, fontWeight: "900", color: "#111" }}>{title}</Text>
      <Text style={{ marginTop: 6, color: "#666", fontWeight: "700" }}>{subtitle}</Text>
    </Pressable>
  );
}

export default function DeviceDashboard() {
  const router = useRouter();
  const { deviceId } = useLocalSearchParams<{ deviceId: string }>();

  const [deviceName, setDeviceName] = useState("");
  const [latest, setLatest] = useState<DoorEvent | null>(null);
  const [face, setFace] = useState<FaceDoc | null>(null);

  const [loading, setLoading] = useState(true);
  const [photoUrl, setPhotoUrl] = useState("");
  const [photoErr, setPhotoErr] = useState("");

  // Kick to home/login if auth goes away
  useEffect(() => {
    const unsub = onAuthStateChanged(auth, (u) => {
      if (!u) router.replace("/");
    });
    return unsub;
  }, [router]);

  // Device display name (Front Door)
  useEffect(() => {
    if (!deviceId) return;

    const devRef = doc(db, "devices", String(deviceId));
    const unsub = onSnapshot(devRef, (snap) => {
      const data = snap.data() as any;
      setDeviceName(data?.name ?? "");
    });

    return unsub;
  }, [deviceId]);

  // Most recent event
  useEffect(() => {
    if (!deviceId) return;

    setLoading(true);

    const q = query(
      collection(db, "devices", String(deviceId), "events"),
      orderBy("createdAt", "desc"),
      limit(1)
    );

    const unsub = onSnapshot(
      q,
      (snap) => {
        const d = snap.docs[0];
        if (!d) {
          setLatest(null);
          setLoading(false);
          return;
        }
        setLatest({ id: d.id, ...(d.data() as any) });
        setLoading(false);
      },
      () => {
        setLatest(null);
        setLoading(false);
      }
    );

    return unsub;
  }, [deviceId]);

  // Join face doc by SAME ID as latest event
  useEffect(() => {
    if (!deviceId || !latest?.id) {
      setFace(null);
      return;
    }

    const faceRef = doc(db, "devices", String(deviceId), "faces", String(latest.id));
    const unsub = onSnapshot(
      faceRef,
      (snap) => setFace(snap.exists() ? ((snap.data() as any) ?? null) : null),
      () => setFace(null)
    );

    return unsub;
  }, [deviceId, latest?.id]);

  // Load photo
  useEffect(() => {
    setPhotoUrl("");
    setPhotoErr("");

    if (!latest?.photoPath) return;

    let cancelled = false;

    (async () => {
      try {
        const url = await getDownloadURL(storageRef(storage, latest.photoPath!));
        if (!cancelled) setPhotoUrl(url);
      } catch (e: any) {
        if (!cancelled) setPhotoErr(e?.code ?? "photo-error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [latest?.photoPath]);

  const badgeLabel = useMemo(() => getPersonLabel(latest, face), [latest, face]);

  async function handleLogout() {
    await signOut(auth);
    router.replace("/");
  }

  if (!deviceId) {
    return (
      <Screen>
        <Text style={{ fontWeight: "900" }}>No deviceId</Text>
      </Screen>
    );
  }

  return (
    <Screen>
      {/* Top bar */}
      <View style={{ flexDirection: "row", alignItems: "center" }}>
        <Pressable onPress={() => router.back()} style={{ flex: 1 }}>
          <Text style={{ color: "#111", fontWeight: "900", fontSize: 16 }}>← Back</Text>
        </Pressable>

        <Pressable onPress={handleLogout}>
          <Text style={{ color: "#111", fontWeight: "900", fontSize: 16 }}>Logout</Text>
        </Pressable>
      </View>

      {/* Title */}
      <Text style={{ marginTop: 14, fontSize: 44, fontWeight: "900", color: "#111" }}>
        {deviceName || "Front Door"}
      </Text>

      {/* Main card: photo + date + person badge */}
      {loading ? (
        <View style={{ marginTop: 18 }}>
          <ActivityIndicator />
        </View>
      ) : !latest ? (
        <View
          style={{
            marginTop: 18,
            borderWidth: 1,
            borderColor: "#e6e6e6",
            borderRadius: 22,
            padding: 16,
            backgroundColor: "#fff",
          }}
        >
          <Text style={{ color: "#666", fontWeight: "700" }}>No notifications yet.</Text>
        </View>
      ) : (
        <Pressable
          onPress={() => router.push(`/device/${String(deviceId)}/event/${latest.id}`)}
          style={({ pressed }) => ({
            marginTop: 18,
            borderWidth: 1,
            borderColor: "#e6e6e6",
            borderRadius: 22,
            padding: 14,
            backgroundColor: "#fff",
            opacity: pressed ? 0.8 : 1,
          })}
        >
          <View
            style={{
              width: "100%",
              height: 250,
              borderRadius: 18,
              backgroundColor: "#eee",
              overflow: "hidden",
              justifyContent: "center",
              alignItems: "center",
            }}
          >
            {photoUrl ? (
              <Image source={{ uri: photoUrl }} style={{ width: "100%", height: "100%" }} resizeMode="cover" />
            ) : (
              <Text style={{ color: "#777", fontWeight: "900" }}>
                {photoErr ? "Photo unavailable" : "Loading…"}
              </Text>
            )}
          </View>

          <View
            style={{
              marginTop: 12,
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <Text style={{ color: "#666", fontWeight: "800", fontSize: 16 }}>
              {formatTimestamp(latest.createdAt)}
            </Text>

            <PersonBadge label={badgeLabel} />
          </View>
        </Pressable>
      )}

      {/* Actions */}
      <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 16 }}>
        <ActionCard
          title="People"
          subtitle="Known / Unknown"
          onPress={() => router.push(`/device/${String(deviceId)}/people`)}
        />
        <ActionCard
          title="Notifications"
          subtitle="Past alerts"
          onPress={() => router.push(`/device/${String(deviceId)}/notifications`)}
        />
      </View>
    </Screen>
  );
}