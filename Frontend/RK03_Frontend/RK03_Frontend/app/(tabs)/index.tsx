import React, { useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  TextInput,
  Pressable,
  FlatList,
  ActivityIndicator,
} from "react-native";
import { onAuthStateChanged, signInWithEmailAndPassword, signOut, User } from "firebase/auth";
import { collection, doc, getDoc, onSnapshot } from "firebase/firestore";
import { auth, db } from "../../src/firebase";
import { useRouter } from "expo-router";

type UserDevice = {
  id: string;      // deviceId (doc id)
  role?: string;   // "owner"
  name?: string;   // from /devices/{deviceId}.name
};

export default function HomeScreen() {
  const router = useRouter();

  // auth
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(true);

  // login form
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loginStatus, setLoginStatus] = useState<string>("");

  // devices
  const [devices, setDevices] = useState<UserDevice[]>([]);
  const [devicesLoading, setDevicesLoading] = useState(false);

  const signedIn = useMemo(() => !!user, [user]);

  // 1) Listen for login/logout
  useEffect(() => {
    const unsub = onAuthStateChanged(auth, (u) => {
      setUser(u);
      setAuthLoading(false);
      setLoginStatus("");
    });
    return unsub;
  }, []);

  // 2) When signed in, listen to /users/{uid}/devices
  useEffect(() => {
    if (!user) {
      setDevices([]);
      return;
    }

    setDevicesLoading(true);

    const devicesCol = collection(db, "users", user.uid, "devices");

    const unsub = onSnapshot(
      devicesCol,
      async (snap) => {
        const baseList: UserDevice[] = snap.docs.map((d) => ({
          id: d.id,
          ...(d.data() as any),
        }));

        // fetch device names from /devices/{deviceId}
        const withNames = await Promise.all(
          baseList.map(async (item) => {
            try {
              const devSnap = await getDoc(doc(db, "devices", item.id));
              const name = devSnap.exists() ? (devSnap.data() as any).name : undefined;
              return { ...item, name };
            } catch {
              return item;
            }
          })
        );

        setDevices(withNames);
        setDevicesLoading(false);
      },
      (err) => {
        setDevicesLoading(false);
        setLoginStatus("Devices error: " + err.message);
      }
    );

    return unsub;
  }, [user]);

  async function handleLogin() {
    setLoginStatus("");
    try {
      if (!email.trim() || !password) {
        setLoginStatus("Enter email and password.");
        return;
      }
      await signInWithEmailAndPassword(auth, email.trim(), password);
      await auth.currentUser?.getIdToken(true);

      // onAuthStateChanged will update UI
    } catch (e: any) {
      setLoginStatus(e.message);
    }
  }

  async function handleLogout() {
    await signOut(auth);
  }

  if (authLoading) {
    return (
      <View style={{ flex: 1, backgroundColor: "#fff", justifyContent: "center", alignItems: "center" }}>
        <ActivityIndicator />
        <Text style={{ marginTop: 12, color: "#111" }}>Loading…</Text>
      </View>
    );
  }

  // --------- LOGGED OUT UI ----------
  if (!signedIn) {
    return (
      <View style={{ flex: 1, backgroundColor: "#fff", padding: 24, paddingTop: 70 }}>
        <Text style={{ fontSize: 28, fontWeight: "700", color: "#111" }}>AI Doorbell</Text>
        <Text style={{ marginTop: 8, color: "#333" }}>Sign in to continue</Text>

        <TextInput
          value={email}
          onChangeText={setEmail}
          placeholder="Email"
          autoCapitalize="none"
          keyboardType="email-address"
          style={{
            marginTop: 20,
            borderWidth: 1,
            borderColor: "#ddd",
            borderRadius: 12,
            padding: 12,
          }}
        />

        <TextInput
          value={password}
          onChangeText={setPassword}
          placeholder="Password"
          secureTextEntry
          style={{
            marginTop: 12,
            borderWidth: 1,
            borderColor: "#ddd",
            borderRadius: 12,
            padding: 12,
          }}
        />

        <Pressable
          onPress={handleLogin}
          style={{
            marginTop: 14,
            backgroundColor: "#111",
            padding: 12,
            borderRadius: 12,
            alignItems: "center",
          }}
        >
          <Text style={{ color: "#fff", fontWeight: "700" }}>Login</Text>
        </Pressable>

        {!!loginStatus && (
          <Text style={{ marginTop: 12, color: "#b00020" }}>{loginStatus}</Text>
        )}

        <Text style={{ marginTop: 18, color: "#666" }}>
          Tip: Create test users in Firebase Console → Authentication → Users.
        </Text>
      </View>
    );
  }

  // --------- LOGGED IN UI ----------
  return (
    <View style={{ flex: 1, backgroundColor: "#fff", padding: 24, paddingTop: 60 }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <Text style={{ fontSize: 22, fontWeight: "800", color: "#111" }}>My Devices</Text>

        <Pressable onPress={handleLogout} style={{ padding: 10 }}>
          <Text style={{ color: "#111", fontWeight: "700" }}>Logout</Text>
        </Pressable>
      </View>

      {devicesLoading ? (
        <View style={{ marginTop: 20 }}>
          <ActivityIndicator />
          <Text style={{ marginTop: 10, color: "#333" }}>Loading devices…</Text>
        </View>
      ) : (
        <FlatList
          style={{ marginTop: 16 }}
          data={devices}
          keyExtractor={(item) => item.id}
          ListEmptyComponent={
            <Text style={{ marginTop: 20, color: "#333" }}>
              No devices found. Create a mapping at users/{`{uid}`}/devices/{`{deviceId}`}.
            </Text>
          }
          renderItem={({ item }) => (
            <Pressable
              onPress={() => router.push(`/device/${item.id}`)}
              style={{
                borderWidth: 1,
                borderColor: "#e5e5e5",
                borderRadius: 14,
                padding: 14,
                marginBottom: 10,
              }}
            >
              <Text style={{ fontSize: 16, fontWeight: "800", color: "#111" }}>
                {item.name ?? item.id}
              </Text>
              <Text style={{ marginTop: 4, color: "#555" }}>
                Role: {item.role ?? "member"}
              </Text>
            </Pressable>
          )}
        />
      )}

      {!!loginStatus && <Text style={{ marginTop: 12, color: "#b00020" }}>{loginStatus}</Text>}
    </View>
  );
}