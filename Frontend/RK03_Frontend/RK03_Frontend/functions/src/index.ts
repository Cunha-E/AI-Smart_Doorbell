import { onDocumentWritten } from "firebase-functions/v2/firestore";
import * as admin from "firebase-admin";

admin.initializeApp();

/**
 * syncDeviceClaims (v2)
 *
 * Trigger: when a doc changes at:
 *   users/{uid}/devices/{deviceId}
 *
 * Copies that mapping into Auth custom claims:
 *   request.auth.token.devices.<deviceId> = "owner" | "member"
 */
export const syncDeviceClaims = onDocumentWritten(
  { document: "users/{uid}/devices/{deviceId}" },
  async (event) => {
    const uid = event.params.uid as string;
    const deviceId = event.params.deviceId as string;

    const afterSnap = event.data?.after;

    // Get existing claims (so we don't overwrite other claims)
    const user = await admin.auth().getUser(uid);
    const currentClaims = (user.customClaims ?? {}) as any;
    const devices = { ...(currentClaims.devices ?? {}) };

    // If doc was deleted, remove claim
    if (!afterSnap || !afterSnap.exists) {
      delete devices[deviceId];
    } else {
      // Doc exists (created/updated) -> set claim
      const data = afterSnap.data() as any;
      const role = (data?.role ?? "member") as string;
      devices[deviceId] = role;
    }

    // Write claims back
    await admin.auth().setCustomUserClaims(uid, {
      ...currentClaims,
      devices,
    });
  }
);
