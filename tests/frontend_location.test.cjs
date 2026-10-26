/* Offline tests execute the real frontend with a tiny DOM and queued geolocation callbacks. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../runorwalk/static/app.js'), 'utf8');
assert.match(source, /\binit\(\);\s*$/);
const script = source.replace(/\binit\(\);\s*$/, '');
const coordinates = {lat: 47.3769, lng: 8.5417, name: 'Current location'};

function harness({googleAvailable = true, secure = true} = {}) {
  const elements = new Map(), requests = [], fetches = [];
  function element(selector) {
    if (!elements.has(selector)) {
      const listeners = new Map(), classes = new Set();
      elements.set(selector, {
        value: '', textContent: '', innerHTML: '', disabled: false, hidden: false,
        attributes: {},
        classList: {
          add: (...names) => names.forEach(name => classes.add(name)),
          remove: (...names) => names.forEach(name => classes.delete(name)),
          toggle: (name, active) => active ? classes.add(name) : classes.delete(name),
        },
        setAttribute(name, value) { this.attributes[name] = value; },
        addEventListener(name, fn) {
          if (!listeners.has(name)) listeners.set(name, []);
          listeners.get(name).push(fn);
        },
        dispatch(name, event) { for (const fn of listeners.get(name) || []) fn(event); },
        reportValidity: () => true,
        querySelectorAll: () => [],
      });
    }
    return elements.get(selector);
  }
  const context = vm.createContext({
    document: {querySelector: element, querySelectorAll: () => [], body: element('body')},
    window: {isSecureContext: secure},
    navigator: {geolocation: {getCurrentPosition(success, failure, options) {
      requests.push({success, failure, options});
    }}},
    AbortController, URL, URLSearchParams,
    fetch: async (url, options) => {
      fetches.push({url, payload: JSON.parse(options.body)});
      // Stop after capturing the real request; route rendering is outside these tests.
      return {ok: false, json: async () => ({error: 'Offline test response'})};
    },
  });
  vm.runInContext(script, context, {filename: 'app.js'});
  vm.runInContext(`globalThis.api = {
    state, locations, journeyLocation, searchJourney,
    get locating() { return locating; }
  };`, context);
  const {api} = context;
  api.state.config = {google_available: googleAvailable};
  for (const [id, value] of Object.entries({origin: 'Previous origin', destination: 'Previous destination',
    'source-mode': 'demo', 'departure-mode': 'now', vma: '16', effort: '65', 'max-run': '10', buffer: '60'})) {
    element(`#${id}`).value = value;
  }
  function fire(id, type = 'click') {
    const target = element(`#${id}`), event = {target, preventDefault() {}};
    target.dispatch(type, event);
    if (['origin', 'destination', 'source-mode'].includes(id) && ['input', 'change'].includes(type)) {
      element('#journey-form').dispatch(type, event);
    }
  }
  function succeed(index = requests.length - 1, latitude = coordinates.lat, longitude = coordinates.lng) {
    requests[index].success({coords: {latitude, longitude, accuracy: 15}});
  }
  return {api, element: id => element(`#${id}`), fire, requests, fetches, succeed};
}

test('success keeps coordinates, switches source only after success, and waits for explicit search', async () => {
  const h = harness();
  h.fire('use-location');
  assert.equal(h.element('source-mode').value, 'demo');
  assert.equal(h.element('origin').value, 'Previous origin');
  assert.equal(h.requests.length, 1);
  assert.equal(h.fetches.length, 0);
  h.succeed();
  assert.equal(h.api.locating, false);
  assert.equal(h.element('source-mode').value, 'google');
  assert.equal(h.element('origin').value, 'Current location');
  assert.equal(h.fetches.length, 0, 'Location selection must not make a billable route request');
  await h.api.searchJourney();
  assert.equal(h.fetches.length, 1);
  assert.equal(h.fetches[0].url, '/api/plan');
  assert.deepEqual(h.fetches[0].payload.origin, coordinates);
  assert.equal(h.fetches[0].payload.destination, 'Previous destination');
  assert.equal(h.fetches[0].payload.mode, 'google');
});

test('denial preserves the previous address, mode, and any previous coordinate selection', () => {
  const h = harness();
  h.fire('use-location');
  h.requests[0].failure({code: 1});
  assert.equal(h.api.locating, false);
  assert.equal(h.api.journeyLocation('origin'), 'Previous origin');
  assert.equal(h.element('source-mode').value, 'demo');
  assert.match(h.element('location-status').textContent, /denied/i);
  h.fire('use-location');
  h.succeed();
  const previous = h.api.journeyLocation('origin');
  h.fire('use-location');
  h.requests[2].failure({code: 1});
  assert.equal(h.api.journeyLocation('origin'), previous);
  assert.equal(h.fetches.length, 0);
});

for (const action of ['cancel', 'edit', 'swap', 'change source']) {
  test(`${action} invalidates a pending location callback`, () => {
    const h = harness();
    h.fire('use-location');
    if (action === 'cancel') h.fire('use-location');
    if (action === 'edit') { h.element('origin').value = 'Manually chosen origin'; h.fire('origin', 'input'); }
    if (action === 'swap') h.fire('swap');
    if (action === 'change source') h.fire('source-mode', 'change');
    const expected = h.element('origin').value;
    h.succeed(0);
    h.requests[0].failure({code: 1});
    assert.equal(h.api.locating, false);
    assert.equal(h.api.journeyLocation('origin'), expected);
    assert.equal(h.element('source-mode').value, 'demo');
    assert.equal(h.element('location-status').textContent, '');
    assert.equal(h.fetches.length, 0);
  });
}

test('cancel and retry ignore the first request without finishing the new request', () => {
  const h = harness();
  h.fire('use-location');
  h.fire('use-location');
  h.fire('use-location');
  h.succeed(0, 40, 7);
  h.requests[0].failure({code: 3});
  assert.equal(h.api.locating, true);
  assert.equal(h.api.journeyLocation('origin'), 'Previous origin');
  h.succeed(1);
  assert.equal(h.api.locating, false);
  assert.equal(h.api.journeyLocation('origin').lat, coordinates.lat);
});

test('swapping retains coordinate backing, and editing clears only the edited endpoint', async () => {
  const h = harness();
  h.fire('use-location');
  h.succeed();
  h.fire('swap');
  assert.equal(h.api.journeyLocation('origin'), 'Previous destination');
  assert.equal(h.element('destination').value, 'Current location');
  h.element('origin').value = 'Edited start';
  h.fire('origin', 'input');
  await h.api.searchJourney();
  assert.equal(h.fetches[0].payload.origin, 'Edited start');
  assert.deepEqual(h.fetches[0].payload.destination, coordinates);
  h.element('destination').value = 'Edited destination';
  h.fire('destination', 'input');
  assert.equal(h.api.journeyLocation('destination'), 'Edited destination');
  assert.equal(h.api.locations.destination, null);
  h.fire('use-location');
  h.succeed();
  h.element('origin').value = 'Edited again';
  h.fire('origin', 'input');
  assert.equal(h.api.locations.origin, null);
  assert.equal(h.api.journeyLocation('origin'), 'Edited again');
});

test('form submission and direct search are blocked while location is pending', async () => {
  const h = harness();
  h.fire('use-location');
  assert.equal(h.element('find-button').disabled, true);
  h.fire('journey-form', 'submit');
  await h.api.searchJourney();
  assert.equal(h.fetches.length, 0);
  assert.equal(h.api.locating, true);
  h.fire('use-location');
  await h.api.searchJourney();
  assert.equal(h.fetches.length, 1);
  assert.equal(h.fetches[0].payload.origin, 'Previous origin');
});

for (const config of [{googleAvailable: false}, {secure: false}]) {
  test(`unavailable prerequisites do not request location: ${JSON.stringify(config)}`, () => {
    const h = harness(config);
    h.fire('use-location');
    assert.equal(h.requests.length, 0);
    assert.equal(h.fetches.length, 0);
    assert.equal(h.api.journeyLocation('origin'), 'Previous origin');
    assert.equal(h.element('source-mode').value, 'demo');
    assert.equal(h.api.locating, false);
    assert.ok(h.element('location-status').textContent);
  });
}

test('invalid coordinates preserve the address and source instead of starting a route', () => {
  const h = harness();
  h.fire('use-location');
  h.succeed(0, NaN, 8.5);
  assert.equal(h.api.locating, false);
  assert.equal(h.api.journeyLocation('origin'), 'Previous origin');
  assert.equal(h.element('source-mode').value, 'demo');
  assert.equal(h.fetches.length, 0);
});
