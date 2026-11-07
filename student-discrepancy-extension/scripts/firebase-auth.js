import { initializeApp } from "firebase/app";
import {
    indexedDBLocalPersistence,
    initializeAuth
} from "firebase/auth/web-extension";
import { firebaseConfig } from "./firebase-config.js";

export const app = initializeApp(firebaseConfig);
export const auth = initializeAuth(app, {
    persistence: indexedDBLocalPersistence
});

const authInitialization = auth.authStateReady();

/**
 * Wait until Firebase has restored its persisted user before reading it.
 * Consumers should use this helper instead of reading auth.currentUser
 * during module initialization.
 */
export async function waitForAuthInitialization() {
    await authInitialization;
    return auth.currentUser;
}
