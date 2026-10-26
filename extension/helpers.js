/* Shared pure helpers. No Google data is read beyond the current page URL. */
(function (scope) {
  "use strict";
  const DEFAULT_PLANNER_URL = "http://127.0.0.1:8787/";

  function isGoogleMapsURL(value) {
    try {
      const url = new URL(value);
      const googleHost = /^(?:www\.|maps\.)?google\.(?:com|[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2})$/i.test(url.hostname);
      return url.protocol === "https:" && googleHost &&
        (url.hostname.startsWith("maps.") || /^\/maps(?:\/|$)/.test(url.pathname));
    } catch {
      return false;
    }
  }

  function decodePlace(value) {
    try {
      return decodeURIComponent(value.replace(/\+/g, " ")).trim().slice(0, 500);
    } catch {
      return value.replace(/\+/g, " ").trim().slice(0, 500);
    }
  }

  function extractRoute(value) {
    if (!isGoogleMapsURL(value)) return { origin: "", destination: "", isMaps: false };
    const url = new URL(value);
    let origin = url.searchParams.get("origin") || url.searchParams.get("saddr") || "";
    let destination = url.searchParams.get("destination") || url.searchParams.get("daddr") || "";
    const marker = "/maps/dir/";
    if (!origin && !destination && url.pathname.includes(marker)) {
      const segments = url.pathname.split(marker)[1].split("/");
      const places = [];
      for (const segment of segments) {
        if (segment.startsWith("@") || segment.startsWith("data=") || segment.startsWith("am=")) break;
        places.push(decodePlace(segment));
      }
      while (places.length > 1 && !places[places.length - 1]) places.pop();
      if (places.length >= 2) {
        origin = places[0];
        destination = places[places.length - 1];
      }
    }
    return { origin: origin.trim().slice(0, 500), destination: destination.trim().slice(0, 500), isMaps: true };
  }

  function validatePlannerURL(value) {
    let url;
    try {
      url = new URL(value);
    } catch {
      throw new Error("Enter a full planner URL, such as http://127.0.0.1:8787/.");
    }
    const isLoopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if (url.username || url.password || !(url.protocol === "https:" || (url.protocol === "http:" && isLoopback))) {
      throw new Error("Use HTTPS, or HTTP on localhost / 127.0.0.1.");
    }
    url.search = "";
    url.hash = "";
    return url.href;
  }

  function buildPlannerURL(base, route) {
    const url = new URL(validatePlannerURL(base || DEFAULT_PLANNER_URL));
    for (const key of ["origin", "destination"]) {
      const value = typeof route?.[key] === "string" ? route[key].trim().slice(0, 500) : "";
      if (value) url.searchParams.set(key, value);
    }
    return url.href;
  }

  const api = { DEFAULT_PLANNER_URL, isGoogleMapsURL, extractRoute, validatePlannerURL, buildPlannerURL };
  scope.RunMapExtension = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
