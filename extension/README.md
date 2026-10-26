# RunMap Chrome extension

This Manifest V3 extension sends the starting point and destination from a Google Maps route to your RunMap planner. The planner compares transport journeys using your selected running profile. The extension does not modify Google's route calculations or copy its timetable results.

## Install

1. Start the RunMap web server as described in the project README. The default address is `http://127.0.0.1:8787/`.
2. Open `chrome://extensions` in Chrome or a Chromium browser.
3. Enable **Developer mode**, choose **Load unpacked**, and select this `extension` folder.
4. Pin **RunMap** in the browser's extensions menu.
5. Open a Google Maps directions page. Click **Try running connections**, or click the toolbar icon to review and edit both stops before opening the planner.

Reload any Google Maps tab that was already open before installation. If you edit extension files, click **Reload** on the extension card, then reload Google Maps.

## How it works

- Reads endpoints from Google Maps `/maps/dir/A/B` links or the `origin` / `destination` query parameters (also legacy `saddr` / `daddr`).
- Opens `http://127.0.0.1:8787/?origin=…&destination=…` in a new tab.
- The on-page button is enabled for Google Maps on `.com`, `.ch`, `.fr`, `.de`, and `.co.uk`. The toolbar popup supports other standard Google country domains too.
- For multiple-stop routes, only the first and last stops are imported. Intermediate waypoints, selected departure times, route preferences, and transport selections are not transferred.
- An empty endpoint or “Your location” may need replacing with an address or stop name in the popup or planner. Shortened Maps share links must first be opened so the browser resolves the full route URL.
- Set **Planner settings → RunMap address** to a different local port or your own HTTPS deployment. Only the address is saved locally; journeys are not retained by the extension. Choose an address you trust: opening it includes your route in the URL.
- The local server must be running. A browser connection error usually means it has not been started or the configured port is wrong.

## Permissions and privacy

`activeTab` lets the toolbar popup read the active URL when you click it. `storage` saves the planner address. The declared content script runs only on the listed Google Maps domains, where it adds the RunMap button; it reads no page content, schedules, account details, or browsing history. There are no remote scripts, analytics, API keys, or paid browser services.

The extension cannot guarantee a faster route: transit coverage, schedules, path availability, and the routing model belong to the RunMap planner. It is an independent companion and is not affiliated with Google.

## Validation

Run `node --test extension/helpers.test.cjs` from the project root for URL import and destination validation checks. Run `node --check` against each `.js` file for syntax validation. Chrome must still be used for an unpacked-extension smoke test.

Implementation references: [Chrome action popups](https://developer.chrome.com/docs/extensions/reference/api/action), [activeTab](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab), [content scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts), [storage](https://developer.chrome.com/docs/extensions/reference/api/storage).
