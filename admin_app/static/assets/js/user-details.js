// user-details.js

import { db } from './firebase-config';  // Import Firestore instance from firebase-config
import { doc, getDoc } from 'firebase/firestore';  // Import Firestore methods

// Get the userId from URL query parameter
const urlParams = new URLSearchParams(window.location.search);
const userId = urlParams.get('userId');  // Assuming the userId is passed in the URL

window.onload = async function() {
  try {
    if (userId) {
      const userRef = doc(db, "users", userId);  // Reference to the user's document in the Firestore "users" collection
      const userSnap = await getDoc(userRef);  // Get the user document

      if (userSnap.exists()) {
        const userData = userSnap.data();  // Get the user data
        displayUserDetails(userData);  // Call the function to display the data
      } else {
        console.log("No such document!");
      }
    }
  } catch (error) {
    console.error("Error fetching user data:", error);
  }
};

// Function to display user data on the page
function displayUserDetails(userData) {
  // Get references to the HTML elements where the user data will be displayed
  document.getElementById("fullName").textContent = userData.fullName;
  document.getElementById("email").textContent = userData.email;
  document.getElementById("mobileNumber").textContent = userData.mobileNumber;
  document.getElementById("location").textContent = userData.location;
  document.getElementById("role").textContent = userData.role;
  document.getElementById("vehicleCategory").textContent = userData.vehicleCategory;
  document.getElementById("vehicleNumber").textContent = userData.vehicleNumber;
  // Add more fields as required...
}
