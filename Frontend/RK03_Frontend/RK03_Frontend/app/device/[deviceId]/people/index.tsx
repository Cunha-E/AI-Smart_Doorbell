import React, { useEffect, useMemo, useState } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { collection, onSnapshot, orderBy, query, limit } from "firebase/firestore";
import { db } from "@/src/firebase";
import { Screen } from "@/components/ui/Screen";

type FaceDoc = {
  id: string;
  status?: "known" | "unknown";
  name?: string;
  photoPath?: string;
  createdAt?: any;
};

function FolderCard({
  title,
  count,
  subtitle,
  onPress,
}: {
  title: string;
  count: number;
  subtitle: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        borderWidth: 1,
        borderColor: "#e6e6e6",
        borderRadius: 22,
        padding: 18,
        backgroundColor: "#fff",
        opacity: pressed ? 0.8 : 1,
        marginTop: 14,
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
      })}
    >
      <View style={{ flex: 1 }}>
        <Text style={{ fontSize: 22, fontWeight: "900", color: "#111" }}>{title}</Text>
        <Text style={{ marginTop: 6, color: "#666", fontWeight: "700" }}>{subtitle}</Text>
      </View>

      <View style={{ alignItems: "flex-end" }}>
        <Text style={{ fontSize: 22, fontWeight: "900", color: "#111" }}>{count}</Text>
        <Text style={{ marginTop: 6, color: "#111", fontWeight: "900", fontSize: 18 }}>›</Text>
      </View>
    </Pressable>
  );
}

export default function PeopleFoldersScreen() {
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
        setFaces(snap.docs.map((d) => ({ id: d.id, ...(d.data() as any) })));
        setLoading(false);
      },
      (e) => {
        setErr(e.message);
        setLoading(false);
      }
    );

    return unsub;
  }, [deviceId]);

  const knownCount = useMemo(() => faces.filter((f) => f.status === "known").length, [faces]);
  const unknownCount = useMemo(() => faces.filter((f) => f.status !== "known").length, [faces]);

  return (
    <Screen>
      <Pressable onPress={() => router.back()} style={{ marginBottom: 12 }}>
        <Text style={{ color: "#111", fontWeight: "900", fontSize: 16 }}>← Back</Text>
      </Pressable>

      <Text style={{ fontSize: 44, fontWeight: "900", color: "#111" }}>People</Text>
      <Text style={{ marginTop: 8, color: "#666", fontWeight: "700" }}>
        Choose a folder.
      </Text>

      {loading ? (
        <View style={{ marginTop: 16 }}>
          <ActivityIndicator />
        </View>
      ) : err ? (
        <Text style={{ marginTop: 16, color: "#b00020", fontWeight: "800" }}>{err}</Text>
      ) : (
        <>
          <FolderCard
            title="Known"
            count={knownCount}
            subtitle="People you’ve labeled"
            onPress={() => router.push(`/device/${String(deviceId)}/people/known`)}
          />
          <FolderCard
            title="Unknown"
            count={unknownCount}
            subtitle="Faces to review"
            onPress={() => router.push(`/device/${String(deviceId)}/people/unknown`)}
          />
        </>
      )}
    </Screen>
  );
}
