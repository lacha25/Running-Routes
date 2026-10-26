"use strict";
const helpers = RunMapExtension;
const originInput = document.getElementById("origin");
const destinationInput = document.getElementById("destination");
const plannerInput = document.getElementById("planner-url");
const feedback = document.getElementById("feedback");
let plannerUrl = helpers.DEFAULT_PLANNER_URL;

function showFeedback(message, isError = false) {
  feedback.textContent = message;
  feedback.classList.toggle("error", isError);
}

async function initialize() {
  plannerInput.value = plannerUrl;
  try {
    const saved = await chrome.storage.local.get({ plannerUrl });
    plannerUrl = helpers.validatePlannerURL(saved.plannerUrl);
    plannerInput.value = plannerUrl;
  } catch {
    showFeedback("Using the default planner address. Check settings if needed.");
  }
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const route = helpers.extractRoute(tab?.url || "");
    originInput.value = route.origin;
    destinationInput.value = route.destination;
    document.getElementById("source-status").textContent = route.origin && route.destination
      ? "Route imported from Google Maps"
      : route.isMaps ? "Choose a route in Maps or enter your stops below."
        : "Enter your stops, or open a route in Google Maps.";
  } catch {
    document.getElementById("source-status").textContent = "Enter your starting point and destination.";
  }
}

document.getElementById("swap").addEventListener("click", () => {
  [originInput.value, destinationInput.value] = [destinationInput.value, originInput.value];
});

document.getElementById("route-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const origin = originInput.value.trim();
  const destination = destinationInput.value.trim();
  if (!origin || !destination) {
    showFeedback("Enter both a starting point and destination.", true);
    (!origin ? originInput : destinationInput).focus();
    return;
  }
  const button = document.getElementById("open-planner");
  button.disabled = true;
  try {
    await chrome.tabs.create({ url: helpers.buildPlannerURL(plannerUrl, { origin, destination }) });
    window.close();
  } catch (error) {
    showFeedback(error.message || "Could not open RunMap.", true);
  } finally {
    button.disabled = false;
  }
});

document.getElementById("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const validated = helpers.validatePlannerURL(plannerInput.value.trim());
    await chrome.storage.local.set({ plannerUrl: validated });
    plannerUrl = validated;
    plannerInput.value = validated;
    showFeedback("Planner address saved.");
  } catch (error) {
    showFeedback(error.message || "Could not save the planner address.", true);
  }
});

initialize();
