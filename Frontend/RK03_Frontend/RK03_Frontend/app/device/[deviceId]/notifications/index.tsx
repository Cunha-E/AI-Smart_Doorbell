import React, { useEffect, useMemo, useState } from "react";
import { View, Text, FlatList, ActivityIndicator, Pressable, Image } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { collection, onSnapshot, orderBy, query, limit } from "firebase/firestore";
import { getDownloadURL, ref as storageRef } from "firebase/storage";
import { db, storage } from "@/src/firebase";
import { Screen } from "@/components/ui/Screen";

type DoorEvent = {
  id: string;
  createdAt?: any;
  type?: string;   // "ring" | "motion"
  result?: string; // could be "unknown | known"
  photoPath?: string;
  personName?: string; // optional (if you ever store it on events)
};

type FaceDoc = {
  id: string;
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

    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");

    let h = d.getHours();
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12;
    if (h === 0) h = 12;

    const min = String(d.getMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}, ${h}:${min} ${ampm}`;
  } catch {
    return "—";
  }
}

function normalizeResult(result?: string) {
  const r = (result ?? "").toLowerCase().trim();

  //"unknown | known" contains "unknown" so this returns Unknown.
  if (r.includes("known") && !r.includes("unknown")) return "Known";
  if (r.includes("unknown")) return "Unknown";
  if (r === "known") return "Known";
  if (r === "unknown") return "Unknown";

  return "Unknown";
}

function PersonBadge({ label }: { label: string }) {
  const isKnown = label !== "Unknown";

  return (
    <View
      style={{
        backgroundColor: isKnown ? "rgba(0,160,90,0.15)" : "rgba(255,140,0,0.15)",
        paddingHorizontal: 10,
        paddingVertical: 6,
        borderRadius: 999,
        maxWidth: 140,
      }}
    >
      <Text
        style={{
          color: isKnown ? "#00a05a" : "#ff8c00",
          fontWeight: "900",
          fontSize: 12,
        }}
        numberOfLines={1}
      >
        {label}
      </Text>
    </View>
  );
}

// Decide what to show in Notifications badge
function getPersonLabel(event: DoorEvent, face?: FaceDoc) {
  const faceName = (face?.name ?? "").trim();
  if (faceName.length > 0) return faceName;

  const eventName = (event.personName ?? "").trim();
  if (eventName.length > 0) return eventName;

  if (face?.status === "known") return "Known";
  if (face?.status === "unknown") return "Unknown";

  return normalizeResult(event.result);
}

function EventRow({
  item,
  face,
  onOpen,
}: {
  item: DoorEvent;
  face?: FaceDoc;
  onOpen: () => void;
}) {
  const [thumbUrl, setThumbUrl] = useState("");
  const [thumbErr, setThumbErr] = useState("");

  useEffect(() => {
    setThumbUrl("");
    setThumbErr("");
    if (!item.photoPath) return;

    let cancelled = false;

    (async () => {
      try {
        const u = await getDownloadURL(storageRef(storage, item.photoPath!));
        if (!cancelled) setThumbUrl(u);
      } catch (e: any) {
        if (!cancelled) setThumbErr(e?.message ?? "photo failed");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [item.photoPath]);

  const typeLabel = (item.type ?? "ring").toUpperCase();
  const personLabel = getPersonLabel(item, face);

  return (
    <Pressable
      onPress={onOpen}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        padding: 14,
        borderWidth: 1,
        borderColor: "#e6e6e6",
        borderRadius: 18,
        backgroundColor: "#fff",
        opacity: pressed ? 0.75 : 1,
        marginBottom: 12,
      })}
    >
      {/* Photo */}
      <View
        style={{
          width: 64,
          height: 64,
          borderRadius: 16,
          backgroundColor: "#eee",
          overflow: "hidden",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {thumbUrl ? (
          <Image source={{ uri: thumbUrl }} style={{ width: "100%", height: "100%" }} resizeMode="cover" />
        ) : (
          <Text style={{ color: "#888", fontWeight: "900" }}>{thumbErr ? "!" : "—"}</Text>
        )}
      </View>

      {/* Text */}
      <View style={{ flex: 1 }}>
        <Text style={{ fontWeight: "900", color: "#111", fontSize: 16 }}>
          {typeLabel}
        </Text>
        <Text style={{ marginTop: 6, color: "#666", fontWeight: "700" }}>
          {formatTimestamp(item.createdAt)}
        </Text>
      </View>

      {/* Person badge */}
      <PersonBadge label={personLabel} />

      {/* Chevron */}
      <Text style={{ marginLeft: 4, color: "#111", fontWeight: "900", fontSize: 18 }}>›</Text>
    </Pressable>
  );
}

export default function NotificationsScreen() {
  const router = useRouter();
  const { deviceId } = useLocalSearchParams<{ deviceId: string }>();

  const [loading, setLoading] = useState(true);
  const [events, setEvents] = useState<DoorEvent[]>([]);
  const [faces, setFaces] = useState<FaceDoc[]>([]);
  const [err, setErr] = useState("");

  // Subscribe to events
  useEffect(() => {
    if (!deviceId) return;

    setLoading(true);
    setErr("");

    const eventsCol = collection(db, "devices", String(deviceId), "events");
    const q = query(eventsCol, orderBy("createdAt", "desc"), limit(50));

    const unsub = onSnapshot(
      q,
      (snap) => {
        const list = snap.docs.map((d) => ({ id: d.id, ...(d.data() as any) }));
        setEvents(list);
        setLoading(false);
      },
      (e) => {
        setErr(e.message);
        setLoading(false);
      }
    );

    return unsub;
  }, [deviceId]);

  // Subscribe to faces (so we can show names/status in Notifications by same ID)
  useEffect(() => {
    if (!deviceId) return;

    const facesCol = collection(db, "devices", String(deviceId), "faces");
    const q = query(facesCol, orderBy("updatedAt", "desc"), limit(300));

    const unsub = onSnapshot(
      q,
      (snap) => {
        const list = snap.docs.map((d) => ({ id: d.id, ...(d.data() as any) })) as FaceDoc[];
        setFaces(list);
      },
      () => {
        // ignore faces errors; notifications can still show event.result
      }
    );

    return unsub;
  }, [deviceId]);

  const facesById = useMemo(() => {
    const m: Record<string, FaceDoc> = {};
    for (const f of faces) m[f.id] = f;
    return m;
  }, [faces]);

  return (
    <Screen>
      <Pressable onPress={() => router.back()} style={{ marginBottom: 12 }}>
        <Text style={{ color: "#111", fontWeight: "900", fontSize: 16 }}>← Back</Text>
      </Pressable>

      <Text style={{ fontSize: 34, fontWeight: "900", color: "#111" }}>Past Notifications</Text>

      {loading ? (
        <View style={{ marginTop: 16 }}>
          <ActivityIndicator />
        </View>
      ) : err ? (
        <Text style={{ marginTop: 16, color: "#b00020" }}>{err}</Text>
      ) : (
        <FlatList
          style={{ marginTop: 14 }}
          data={events}
          keyExtractor={(item) => item.id}
          showsVerticalScrollIndicator={false}
          ListEmptyComponent={<Text style={{ marginTop: 16, color: "#666" }}>No events yet.</Text>}
          renderItem={({ item }) => (
            <EventRow
              item={item}
              face={facesById[item.id]}
              onOpen={() => router.push(`/device/${String(deviceId)}/event/${item.id}`)}
            />
          )}
        />
      )}
    </Screen>
  );
}
