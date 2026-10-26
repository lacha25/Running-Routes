const test = require("node:test");
const assert = require("node:assert/strict");
const { extractRoute, validatePlannerURL, buildPlannerURL, isGoogleMapsURL } = require("./helpers.js");

test("imports readable routes and discards Google camera metadata", () => {
  assert.deepEqual(extractRoute("https://www.google.com/maps/dir/Z%C3%BCrich+HB/ETH+Z%C3%BCrich/@47.3,8.5,12z/data=!4m2"), {
    origin: "Zürich HB", destination: "ETH Zürich", isMaps: true,
  });
});
test("imports official and legacy query forms once without corrupting encoded plus", () => {
  assert.equal(extractRoute("https://www.google.ch/maps/dir/?api=1&origin=A%2BB&destination=Z%C3%BCrich+HB").origin, "A+B");
  assert.equal(extractRoute("https://maps.google.com/?saddr=Station+A&daddr=Station+B").destination, "Station B");
});
test("uses outer endpoints, handles empty origin and missing destination", () => {
  assert.equal(extractRoute("https://www.google.com/maps/dir/A/Middle/B/@47,8,10z").destination, "B");
  assert.deepEqual(extractRoute("https://www.google.com/maps/dir//B/"), { origin: "", destination: "B", isMaps: true });
  assert.equal(extractRoute("https://www.google.com/maps/dir/A/").destination, "");
});
test("rejects lookalike sites and unrelated Google pages", () => {
  for (const url of ["https://google.com.evil.test/maps/dir/A/B", "https://www.google.com/search?q=A", "javascript:alert(1)", "not a url"]) {
    assert.equal(isGoogleMapsURL(url), false);
    assert.equal(extractRoute(url).origin, "");
  }
  assert.equal(isGoogleMapsURL("https://www.google.co.uk/maps/dir/A/B"), true);
});
test("accepts HTTPS and local HTTP, rejects remote HTTP and executable schemes", () => {
  for (const url of ["http://127.0.0.1:8787/", "http://localhost:9000/app", "http://[::1]:8787", "https://planner.example/run"]) {
    assert.ok(validatePlannerURL(url));
  }
  for (const url of ["http://example.com", "http://127.0.0.1.evil.test", "javascript:alert(1)", "file:///tmp/a", "https://user:pass@example.com"]) {
    assert.throws(() => validatePlannerURL(url));
  }
});
test("clears stale parameters and encodes imported addresses safely", () => {
  const url = new URL(buildPlannerURL("https://planner.example/run?old=1#old", { origin: "A & B/#", destination: "Zürich HB" }));
  assert.equal(url.searchParams.get("origin"), "A & B/#");
  assert.equal(url.searchParams.get("destination"), "Zürich HB");
  assert.equal(url.searchParams.has("old"), false);
  assert.equal(url.hash, "");
});
