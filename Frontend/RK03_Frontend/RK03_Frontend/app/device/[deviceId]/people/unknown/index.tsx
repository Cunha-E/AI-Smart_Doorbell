import React, { useEffect, useState } from "react";
import { View, Text, FlatList, ActivityIndicator, Pressable, Image } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { collection, onSnapshot, orderBy, query, limit } from "firebase/firestore";
import { getDownloadURL, ref as storageRef } from "firebase/storage";
import { db, storage } from "@/src/firebase";
import { Screen } from "@/components/ui/Screen";

type FaceDoc = {
  id: string;
  status?: "known" | "unknown";
  photoPath?: string;
  createdAt?: any;
};

function FaceTile({
  photoPath,
  onPress,
}: {
  photoPath?: string;
  onPress: () => void;
}) {
  const [url, setUrl] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    setUrl("");
    setErr("");
    if (!photoPath) return;

    let cancelled = false;

    (async () => {
      try {
        const u = await getDownloadURL(storageRef(storage, photoPath));
        if (!cancelled) setUrl(u);
      } catch (e: any) {
        if (!cancelled) setErr(e?.message ?? "photo failed");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [photoPath]);

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        width: "48%",
        borderWidth: 1,
        borderColor: "#e6e6e6",
        borderRadius: 18,
        padding: 12,
        marginBottom: 12,
        backgroundColor: "#fff",
        opacity: pressed ? 0.8 : 1,
      })}
    >
      <View
        style={{
          width: "100%",
          height: 150,
          borderRadius: 16,
          backgroundColor: "#eee",
          overflow: "hidden",
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        {url ? (
          <Image source={{ uri: url }} style={{ width: "100%", height: "100%" }} resizeMode="cover" />
        ) : (
          <Text style={{ color: "#888", fontWeight: "900" }}>{err ? "!" : "—"}</Text>
        )}
      </View>

      <Text style={{ marginTop: 10, fontWeight: "900", color: "#111" }}>Unknown</Text>
      <Text style={{ marginTop: 4, color: "#666", fontWeight: "700" }}>Tap to label</Text>
    </Pressable>
  );
}

export default function UnknownPeopleScreen() {
  const router = useRouter();
  const { deviceId } = useLocalSearchParams<{ deviceId: string }>();

  const [loading, setLoading] = useState(true);
  const [faces, setFaces] = useState<FaceDoc[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!deviceId) return;

    setLoading(true);
    setErr("");

    const colRef = collection(db, "devices", String(deviceId), "faces");
    const q = query(colRef, orderBy("createdAt", "desc"), limit(200));

    const unsub = onSnapshot(
      q,
      (snap) => {
        const all = snap.docs.map((d) => ({ id: d.id, ...(d.data() as any) }));
        setFaces(all.filter((f) => f.status !== "known"));
        setLoading(false);
      },
      (e) => {
        setErr(e.message);
        setLoading(false);
      }
    );

    return unsub;
  }, [deviceId]);

  return (
    <Screen>
      <Pressable onPress={() => router.back()} style={{ marginBottom: 12 }}>
        <Text style={{ color: "#111", fontWeight: "900", fontSize: 16 }}>← Back</Text>
      </Pressable>

      <Text style={{ fontSize: 40, fontWeight: "900", color: "#111" }}>Unknown</Text>

      {loading ? (
        <View style={{ marginTop: 16 }}>
          <ActivityIndicator />
        </View>
      ) : err ? (
        <Text style={{ marginTop: 16, color: "#b00020", fontWeight: "800" }}>{err}</Text>
      ) : faces.length === 0 ? (
        <Text style={{ marginTop: 16, color: "#666", fontWeight: "700" }}>
          No unknown faces right now.
        </Text>
      ) : (
        <FlatList
          style={{ marginTop: 14 }}
          data={faces}
          numColumns={2}
          columnWrapperStyle={{ justifyContent: "space-between" }}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => (
            <FaceTile
              photoPath={item.photoPath}
              onPress={() => router.push(`/device/${String(deviceId)}/faces/${item.id}`)}
            />
          )}
        />
      )}
    </Screen>
  );
}
