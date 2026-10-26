"use strict";
importScripts("helpers.js");

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.type !== "RUNMAP_OPEN" || sender.id !== chrome.runtime.id) return;
  if (!sender.tab || !RunMapExtension.isGoogleMapsURL(sender.url || sender.tab.url || "")) return;

  // Derive the route from Chrome's sender URL, never from a page-supplied message.
  const route = RunMapExtension.extractRoute(sender.url || sender.tab.url);
  chrome.storage.local.get({ plannerUrl: RunMapExtension.DEFAULT_PLANNER_URL })
    .then(({ plannerUrl }) => chrome.tabs.create({
      url: RunMapExtension.buildPlannerURL(plannerUrl, route),
      openerTabId: sender.tab.id,
    }))
    .then(() => respond({ ok: true }))
    .catch((error) => respond({ ok: false, error: error.message || "Could not open RunMap." }));
  return true;
});
