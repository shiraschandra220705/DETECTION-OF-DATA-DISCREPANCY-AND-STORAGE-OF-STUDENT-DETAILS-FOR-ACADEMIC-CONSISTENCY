
import { initializeApp } from "https://www.gstatic.com/firebasejs/13.0.0/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/13.0.0/firebase-auth.js";
import { getFirestore } from "https://www.gstatic.com/firebasejs/13.0.0/firebase-firestore.js";

const firebaseConfig = {
  apiKey: "AIzaSyBRgeexgSveSRxcI0ICcYLK5NIZbPknEKk",
  authDomain: "securoserv-student-records.firebaseapp.com",
  projectId: "securoserv-student-records",
  storageBucket: "securoserv-student-records.firebasestorage.app",
  messagingSenderId: "846380072594",
  appId: "1:846380072594:web:27525e8f58f97d4921704b"
};

const app = initializeApp(firebaseConfig);

export const auth = getAuth(app);
export const db = getFirestore(app);
