'use strict';

const $ = selector => document.querySelector(selector);
const icons = {
  arrow:'M4 12h16m-6-6 6 6-6 6',
  swap:'M8 3v17m-4-4 4 4 4-4M16 21V4m-4 4 4-4 4 4',
  clock:'M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  pin:'M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0M15 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
  locate:'M12 2v3m0 14v3M2 12h3m14 0h3M19 12a7 7 0 1 1-14 0 7 7 0 0 1 14 0M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
  bolt:'m13 2-9 12h7l-1 8 10-13h-7z',
  leaf:'M20 3C8 2 2 8 6 16s16 2 14-13ZM4 21 15 10',
  sun:'M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5',
  heart:'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z',
  info:'M12 11v6m0-10v.1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  run:'M17 4a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0M6 9l4-2 4 3 4 2 3-2M14 10l-4 5-4 1-3 5m7-6 5 2v5M10 7 7 12',
  walk:'M15.5 3.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0M7 12l3-4h4l2 5 4 1M12 8l-2 8-3 6m3-6 5 2 1 4',
  transit:'M6 3h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2ZM4 11h16M8 19l-2 3m10-3 2 3M8 15h.01M16 15h.01M9 6h6',
  route:'M5 17V7a3 3 0 0 1 6 0v10a4 4 0 0 0 8 0V5M7 19a2 2 0 1 1-4 0 2 2 0 0 1 4 0M21 3a2 2 0 1 1-4 0 2 2 0 0 1 4 0',
  settings:'m12 3 3 2h3l1 4 2 3-2 3-1 4h-3l-3 2-3-2H6l-1-4-2-3 2-3 1-4h3zM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
  sliders:'M4 5h16M4 12h16M4 19h16M8 3v4m8 3v4M10 17v4',
  expand:'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M9 9 3 3m12 6 6-6M9 15l-6 6m12-6 6 6',
  beaker:'M9 3v6L3 20h18L15 9V3M7 3h10M7 14h10',
  map:'m3 5 6-2 6 3 6-2v15l-6 2-6-3-6 2zM9 3v15m6-12v15',
  external:'M14 3h7v7m0-7L10 14M10 4H4v16h16v-6',
  check:'m5 12 4 4L20 5',
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[name] || icons.route}"/></svg>`;
document.querySelectorAll('[data-icon]').forEach(el => el.outerHTML = icon(el.dataset.icon));
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const minutes = seconds => Math.max(0, Math.ceil((seconds || 0) / 60));
const distance = meters => meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters || 0)} m`;
const clock = date => new Date(date).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', hour12:false});
const pace = speed => { const s = Math.round(3600 / speed); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2,'0')}`; };
const color = (value, fallback = '#426cb6') => /^#[0-9a-f]{6}$/i.test(value || '') ? value : fallback;
const state = {config:null, profile:'young_athletic', data:null, selected:'best', busy:false, stale:false, sequence:0, controller:null, map:null, mapKind:null, layers:null, googleLayers:[], googlePromise:null, fitted:false};
const locations = {origin:null, destination:null};
let locationRequest = 0;
let locating = false;

function locationMessage(message, error=false) {
  $('#location-status').textContent = message;
  $('#location-status').hidden = !message;
  $('#location-status').classList.toggle('location-error', error);
}

function finishLocating() {
  locating = false;
  $('#use-location').setAttribute('aria-busy', 'false');
  $('#location-label').textContent = 'Use my location';
  $('#find-button').disabled = state.busy;
}

function cancelLocationRequest() {
  locationRequest++;
  if (locating) finishLocating();
  locationMessage('');
}

function journeyLocation(field) {
  return locations[field] || $(`#${field}`).value;
}

function useCurrentLocation() {
  if (locating) { cancelLocationRequest(); return; }
  if (!state.config?.google_available) {
    locationMessage('Connect Google Maps in Setup to use your current location.', true);
    return;
  }
  if (!window.isSecureContext || !navigator.geolocation) {
    locationMessage('Location is unavailable here. Open RunMap at http://127.0.0.1:8787 in your browser, or enter a starting address.', true);
    return;
  }
  const request = ++locationRequest;
  markStale();
  locating = true;
  $('#use-location').setAttribute('aria-busy', 'true');
  $('#location-label').textContent = 'Cancel location request';
  $('#find-button').disabled = true;
  locationMessage('Finding your location… Allow location access if your browser asks.');
  const fail = error => {
    if (request !== locationRequest) return;
    finishLocating();
    const messages = {
      1:'Location access was denied. Allow it in your browser or system settings, or enter a starting address.',
      2:'Your position is unavailable. Try again in your usual browser, or enter a starting address.',
      3:'Finding your location took too long. Try again, or enter a starting address.',
    };
    locationMessage(messages[error?.code] || 'Could not find your location. Try again, or enter a starting address.', true);
  };
  try {
    navigator.geolocation.getCurrentPosition(position => {
      if (request !== locationRequest) return;
      const {latitude:lat, longitude:lng, accuracy} = position.coords;
      if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat)>90 || Math.abs(lng)>180) { fail({code:2}); return; }
      finishLocating();
      locations.origin = {lat, lng, name:'Current location'};
      $('#origin').value = 'Current location';
      $('#source-mode').value = 'google';
      updateSourceMode(false);
      $('#error').hidden = true;
      markStale();
      const estimate = Number.isFinite(accuracy) && accuracy>0 ? ` Estimated accuracy: ${distance(accuracy)}.` : '';
      locationMessage(`Current location selected.${estimate}`);
    }, fail, {enableHighAccuracy:true, timeout:10000, maximumAge:30000});
  } catch (error) { fail(error); }
}

function updatePace() {
  const speed = Number($('#vma').value) * Number($('#effort').value) / 100;
  $('#pace-preview').innerHTML = `${speed > 0 ? pace(speed) : '—'} <small>/km</small>`;
  $('#effort-value').textContent = `${$('#effort').value}% of VMA`;
}

function setProfile(id) {
  const profile = state.config?.profiles.find(item => item.id === id);
  state.profile = id;
  document.querySelectorAll('[data-profile]').forEach(el => { const selected = el.dataset.profile === id; el.classList.toggle('selected', selected); el.setAttribute('aria-pressed', String(selected)); });
  $('#vma').value = profile?.vma_kmh ?? ({young_athletic:16,young_casual:11,forties:12,older:9}[id]);
  updatePace();
}

function markStale() {
  state.stale = Boolean(state.data);
  if (state.busy) {
    state.sequence++;
    state.controller?.abort();
    state.busy = false;
    document.body.classList.remove('loading');
    $('#find-button').disabled = false;
    $('#results').setAttribute('aria-busy','false');
  }
  $('#results').classList.toggle('stale', Boolean(state.data));
  $('#find-label').textContent = state.data ? 'Update my route' : 'Find my fastest route';
  $('#find-button').disabled = locating;
}

function showToast(message) {
  $('#map-toast').textContent = message;
  $('#map-toast').hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => $('#map-toast').hidden = true, 5500);
}

function resetMap() {
  if (state.mapKind === 'leaflet') state.map?.remove();
  state.googleLayers.forEach(layer => layer.setMap(null));
  state.googleLayers = [];
  state.map = null;
  state.layers = null;
  $('#map').replaceChildren();
  state.mapKind = null;
}

async function ensureMap(mode, revision=state.sequence) {
  $('#map-unavailable').hidden = true;
  if (mode === 'google') {
    if (state.mapKind === 'google' && state.map) return;
    resetMap();
    const key = state.config?.google_browser_key;
    if (!key) { $('#map-unavailable').hidden = false; return; }
    try {
      if (!state.googlePromise) state.googlePromise = new Promise((resolve,reject) => {
        window.runMapGoogleReady = resolve;
        window.gm_authFailure = () => { $('#map-unavailable').hidden = false; showToast('Google map authorization failed. Check your browser key restrictions.'); };
        const script = document.createElement('script');
        script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&callback=runMapGoogleReady&loading=async&v=weekly`;
        script.onerror = reject;
        document.head.append(script);
        setTimeout(() => reject(new Error('Google Maps did not load.')),15000);
      });
      await state.googlePromise;
      if (revision !== state.sequence) return;
      state.map = new google.maps.Map($('#map'), {center:{lat:47.377,lng:8.546},zoom:14,disableDefaultUI:true,clickableIcons:false,gestureHandling:'greedy'});
      state.mapKind = 'google';
    } catch { $('#map-unavailable').hidden = false; showToast('The Google map could not load. Your itinerary is still available.'); }
    return;
  }
  if (state.mapKind === 'leaflet' && state.map) return;
  resetMap();
  if (!window.L) { $('#map-unavailable').hidden = false; $('#map-unavailable p').textContent = 'The map library could not load. Reload the page to try again.'; return; }
  state.map = L.map('map', {zoomControl:false, scrollWheelZoom:false, attributionControl:true}).setView([47.374,8.55],14);
  state.mapKind = 'leaflet';
  const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19, attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>'}).addTo(state.map);
  let tileErrors = 0;
  tiles.on('tileerror', () => {if (++tileErrors === 5) showToast('Map tiles are unavailable. Route lines and directions still work.');});
  state.layers = L.featureGroup().addTo(state.map);
}

function selectedRoute() {
  if (!state.data) return null;
  if (state.selected === 'baseline') return state.data.baseline;
  if (state.selected.startsWith('alt-')) return state.data.alternatives[Number(state.selected.slice(4))];
  return state.data.best;
}

function routePath(step) {
  const path = step.path?.length ? step.path : [step.start,step.end];
  return path.filter(point => point && Number.isFinite(point.lat) && Number.isFinite(point.lng));
}

function fitMap() {
  const route = selectedRoute();
  if (!route || !state.map) return;
  const points = route.steps.flatMap(routePath);
  if (!points.length) return;
  const mobile = window.innerWidth <= 760;
  if (state.mapKind === 'leaflet') state.map.fitBounds(points.map(p => [p.lat,p.lng]), {paddingTopLeft:mobile?[30,65]:[65,100],paddingBottomRight:mobile?[70,100]:[110,150],maxZoom:15,animate:false});
  else { const bounds = new google.maps.LatLngBounds(); points.forEach(p => bounds.extend(p)); state.map.fitBounds(bounds, {top:95,right:90,bottom:160,left:75}); }
}

function focusStep(index) {
  const route = selectedRoute();
  if (!route || !state.map) return;
  const step = route.steps[index], points = routePath(step);
  if (!points.length) return;
  if (state.mapKind === 'leaflet') state.map.fitBounds(points.map(p => [p.lat,p.lng]), {padding:[85,100],maxZoom:17});
  else {const bounds = new google.maps.LatLngBounds(); points.forEach(p => bounds.extend(p)); state.map.fitBounds(bounds,90);}
  showToast(step.mode === 'TRANSIT' ? `${step.line?.short_name || step.line?.name || 'Transit'} · ${step.start.name} → ${step.end.name}` : `${step.mode === 'RUN' ? 'Run' : step.mode === 'WAIT' ? 'Wait' : 'Walk'} · ${minutes(step.duration_s)} min`);
  if (window.innerWidth <= 760) $('.map-panel').scrollIntoView({behavior:'smooth',block:'start'});
}

async function renderMap() {
  const data = state.data, route = selectedRoute();
  if (!route) return;
  const revision = state.sequence;
  await ensureMap(data.mode, revision);
  if (!state.map || state.data !== data || revision !== state.sequence) return;
  if (state.mapKind === 'leaflet') state.layers.clearLayers();
  else { state.googleLayers.forEach(layer => layer.setMap(null)); state.googleLayers = []; }
  const map = state.map;
  route.steps.forEach((step, index) => {
    if (step.mode === 'WAIT') return;
    const points = routePath(step);
    if (points.length < 2) return;
    const stroke = step.mode === 'TRANSIT' ? color(step.line?.color) : step.mode === 'RUN' ? '#348a60' : '#96a88a';
    if (state.mapKind === 'leaflet') {
      const latlngs = points.map(point => [point.lat,point.lng]);
      L.polyline(latlngs, {color:'#fff',weight:9,opacity:.9,interactive:false}).addTo(state.layers);
      const line = L.polyline(latlngs, {color:stroke,weight:step.mode === 'TRANSIT'?5:4,dashArray:step.mode === 'TRANSIT'?undefined:'5 8',lineCap:'round',opacity:1}).addTo(state.layers);
      const tooltip = document.createElement('span'); tooltip.textContent = step.mode === 'TRANSIT' ? `${step.line?.short_name || step.line?.name || 'Transit'} to ${step.end.name}` : `${step.mode === 'RUN' ? 'Run' : 'Walk'} ${distance(step.distance_m)} · ${minutes(step.duration_s)} min`;
      line.bindTooltip(tooltip).on('click', () => focusStep(index));
      if (step.mode === 'TRANSIT') [step.start, step.end].forEach(p => L.circleMarker([p.lat,p.lng],{radius:5,color:stroke,weight:3,fillColor:'#fff',fillOpacity:1}).addTo(state.layers));
    } else {
      const dashed = step.mode !== 'TRANSIT';
      const line = new google.maps.Polyline({map,path:points,strokeColor:stroke,strokeOpacity:dashed?0:1,strokeWeight:5,icons:dashed?[{icon:{path:'M 0,-1 0,1',strokeColor:stroke,strokeOpacity:1,scale:2},offset:'0',repeat:'13px'}]:[]});
      line.addListener('click', () => focusStep(index));
      state.googleLayers.push(line);
    }
  });
  const endpoints = [route.steps[0]?.start,route.steps.at(-1)?.end];
  endpoints.forEach((point,index) => {
    if (!point) return;
    const label = index ? 'B' : 'A';
    if (state.mapKind === 'leaflet') L.marker([point.lat,point.lng],{icon:L.divIcon({className:'map-pin',html:`<div class="map-pin-inner"><span class="pin-letter ${index?'destination':''}">${label}</span><span class="pin-label">${escapeHtml(point.name || (index?data.destination.name:data.origin.name))}</span></div>`,iconSize:[1,1],iconAnchor:[0,0]})}).addTo(state.layers);
    else state.googleLayers.push(new google.maps.Marker({map,position:point,label,title:point.name}));
  });
  fitMap();
}

function linePill(line) {
  const background = color(line?.color);
  const channels = [1, 3, 5].map(offset => {
    const value = parseInt(background.slice(offset, offset + 2), 16) / 255;
    return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
  });
  const luminance = channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
  const foreground = luminance > .179 ? '#000000' : '#ffffff';
  return `<span class="line-pill" style="background:${background};color:${foreground}">${escapeHtml(line?.short_name || line?.name || 'Transit')}</span>`;
}

function routeOverview(route) {
  const parts = [];
  route.steps.filter(step => step.mode !== 'WAIT').forEach(step => {
    if (step.mode === 'TRANSIT') parts.push(linePill(step.line));
    else if (parts.length === 0 || step.mode === 'RUN') parts.push(`${icon(step.mode === 'RUN'?'run':'walk')}<span class="run-distance">${distance(step.distance_m)}</span>`);
  });
  return parts.join('<span class="chevron">›</span>');
}

function card(route, id, badge, neutral=false) {
  return `<button type="button" class="route-card ${state.selected===id?'active':''}" data-route="${id}" aria-pressed="${state.selected===id}"><span class="route-card-top"><strong>${minutes(route.duration_s)} <small>min</small></strong><span class="route-badge ${neutral?'neutral':''}">${escapeHtml(badge)}</span></span><span class="route-overview">${routeOverview(route)}</span><span class="route-card-bottom"><span class="card-times">${clock(route.departure)} – ${clock(route.arrival)}</span><span>${route.run_distance_m ? `${distance(route.run_distance_m)} running` : 'Walking connections'} · ${Math.max(0,route.transit_count-1)} ${route.transit_count===2?'transfer':'transfers'}</span></span></button>`;
}

function renderResults() {
  const data = state.data, route = selectedRoute();
  $('#results').hidden = false;
  $('#results').classList.toggle('stale',state.stale);
  $('#departure-label').textContent = `Depart ${clock(data.requested_departure)} · local time`;
  let cards = card(data.best, 'best', data.savings_s>=60 ? `Fastest found · −${Math.floor(data.savings_s/60)} min` : 'Fastest found');
  if (data.baseline && (data.best.run_duration_s > 0 || data.savings_s > 0)) cards += card(data.baseline,'baseline','At a walking pace',true);
  const unique = new Set([data.best.id,data.baseline?.id]);
  let extra = 0;
  (data.alternatives || []).forEach((alt,index) => {if (extra < 1 && !unique.has(alt.id)) { cards += card(alt,`alt-${index}`,'Another connection',true);extra++;unique.add(alt.id);} });
  $('#route-options').innerHTML = cards;
  $('#route-options').querySelectorAll('[data-route]').forEach(button => button.addEventListener('click', () => {state.selected = button.dataset.route; renderResults(); renderMap();}));
  const steps = route.steps.map((step,index) => {
    let title, meta;
    if (step.mode === 'TRANSIT') {
      title = `${linePill(step.line)} ${escapeHtml(step.start.name)} → ${escapeHtml(step.end.name)}`;
      meta = `${minutes(step.duration_s)} min${step.line?.stop_count ? ` · ${step.line.stop_count} stops` : ''}${step.line?.headsign ? ` · toward ${escapeHtml(step.line.headsign)}` : ''}`;
      const agencies = (step.line?.agencies || []).map(agency => escapeHtml(agency.name)).filter(Boolean);
      if (agencies.length) meta += ` · ${agencies.join(', ')}`;
    } else if (step.mode === 'WAIT') {
      title = `Wait at ${escapeHtml(step.start.name)}`;
      meta = `${minutes(step.duration_s)} min · includes time to board`;
    } else {
      title = `${step.mode === 'RUN'?'Run':'Walk'} to ${escapeHtml(step.end.name)}`;
      meta = `${distance(step.distance_m)} · ${minutes(step.duration_s)} min${step.mode==='RUN'?` · ${pace(data.profile.run_speed_kmh)} /km`:''}`;
    }
    const directions = (step.mode === 'RUN' || step.mode === 'WALK') && step.directions?.length > 1 ? `<details class="street-directions"><summary>Street directions</summary><ol>${step.directions.map(text=>`<li>${escapeHtml(text)}</li>`).join('')}</ol></details>` : '';
    return `<li data-mode="${escapeHtml(step.mode)}"><time datetime="${escapeHtml(step.start_time)}">${clock(step.start_time)}</time><span class="timeline-track"><i class="timeline-dot"></i></span><div><button type="button" class="step-button" data-step="${index}" aria-label="Show ${escapeHtml(step.mode.toLowerCase())} leg on map"><span class="step-title">${title}</span><span class="step-meta">${meta}</span></button>${directions}</div></li>`;
  }).join('');
  const mapsUrl = new URL('https://www.google.com/maps/dir/');
  const endpoints = new URLSearchParams((data.google_maps_url || '').split('?')[1] || '');
  mapsUrl.search = new URLSearchParams({api:'1',origin:endpoints.get('origin') || data.origin.name || $('#origin').value,destination:endpoints.get('destination') || data.destination.name || $('#destination').value,travelmode:'transit'});
  $('#journey-details').innerHTML = `<div class="timeline-header"><h3>Your journey, step by step</h3><span>${minutes(route.run_duration_s)} min running</span></div><ol class="timeline">${steps}<li><time>${clock(route.arrival)}</time><span class="timeline-track"><i class="timeline-dot"></i></span><span class="timeline-end">Arrive at ${escapeHtml(data.destination.name)}</span></li></ol><div class="connection-tip">${icon('info')}<span>${data.mode==='demo'?'Illustrative service times and paths. This journey is for exploring the planner.':'Check the stop display before boarding. Service times and actual running conditions can change.'}</span></div><a class="maps-link" href="${escapeHtml(mapsUrl.href)}" target="_blank" rel="noopener">Open endpoints in Google Maps ${icon('external')}</a><p class="maps-note">Google Maps recalculates the journey at walking pace.</p>${data.mode==='google'?'<p class="google-attribution" translate="no">Google Maps</p>':''}`;
  $('#journey-details').querySelectorAll('[data-step]').forEach(button => button.addEventListener('click', () => focusStep(Number(button.dataset.step))));
  $('#search-note').textContent = (data.warnings || []).join(' ') || 'Fastest among the routes checked. Running times include an allowance for crossings.';
  $('#map-city').textContent = data.mode === 'demo' ? 'Zürich, Switzerland' : 'Your Google Maps journey';
  $('#map-subtitle').textContent = data.mode === 'demo' ? 'A smarter way across the city' : 'Transit connections at your running pace';
  $('#map-badge').textContent = data.mode === 'demo' ? 'DEMO NETWORK' : 'GOOGLE MAPS';
  const saved = data.baseline ? Math.max(0,(new Date(data.baseline.arrival)-new Date(route.arrival))/1000) : 0;
  $('#map-summary').hidden = false;
  $('#map-summary').innerHTML = `<span class="summary-icon">${icon(saved>0?'bolt':'route')}</span><div class="summary-copy"><strong>${!data.baseline?'A connection worth running for.':saved>=60?`${Math.floor(saved/60)} minutes back in your day.`:'Your next connection, mapped.'}</strong><span>${!data.baseline?'No walking comparison available.':saved>0?'A little running goes a long way.':'Every connection counts.'}</span></div><span class="summary-divider"></span><div class="summary-stat"><strong>${distance(route.run_distance_m)}</strong><span>total running</span></div><div class="summary-stat"><strong>${clock(route.arrival)}</strong><span>arrival time</span></div>`;
}

async function searchJourney({scroll=false}={}) {
  if (locating) return;
  if (!$('#journey-form').reportValidity()) return;
  const id = ++state.sequence;
  state.controller?.abort();
  state.controller = new AbortController();
  $('#error').hidden = true;
  const departure = $('#departure-mode').value === 'at' ? new Date($('#departure-time').value) : new Date();
  if (!Number.isFinite(departure.getTime())) {$('#error').textContent = 'Choose a departure date and time.';$('#error').hidden=false;return;}
  const payload = {origin:journeyLocation('origin'),destination:journeyLocation('destination'),mode:$('#source-mode').value,departure:departure.toISOString(),profile_id:state.profile,vma_kmh:Number($('#vma').value),effort:Number($('#effort').value)/100,max_run_minutes:Number($('#max-run').value),transfer_buffer_s:Number($('#buffer').value)};
  state.busy = true;
  document.body.classList.add('loading');
  $('#find-button').disabled = true;
  $('#find-label').textContent = payload.mode==='google' ? 'Checking your connections…' : 'Finding your connection…';
  $('#results').setAttribute('aria-busy','true');
  try {
    const response = await fetch('/api/plan', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:state.controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'No route found. Try another journey.');
    if (id !== state.sequence) return;
    state.data = data;
    state.stale = false;
    state.selected = 'best';
    renderResults();
    await renderMap();
    if (scroll) $('#results').scrollIntoView({behavior:'smooth',block:'start'});
  } catch (error) {
    if (error.name === 'AbortError') return;
    $('#error').textContent = error.message === 'Failed to fetch' ? 'RunMap cannot reach its local server. Restart it and try again.' : error.message;
    $('#error').hidden = false;
    $('#results').hidden = true;
    $('#map-summary').hidden = true;
    state.data = null;
    if (state.mapKind === 'leaflet') state.layers?.clearLayers();
    state.googleLayers.forEach(layer => layer.setMap(null));
    state.googleLayers = [];
  } finally {
    if (id === state.sequence) {
      state.busy = false;
      document.body.classList.remove('loading');
      $('#find-button').disabled = locating;
      $('#find-label').textContent = 'Find my fastest route';
      $('#results').setAttribute('aria-busy','false');
    }
  }
}

const dialogs = {
  how: () => `<h2>Make the connection.</h2><p>Public transport is built around timetables. RunMap asks a simple question: what could you catch if you ran the walking parts?</p><h3>01 · Set your pace</h3><p>Choose a starting profile or enter your own VMA. Your planning speed is <strong>VMA × effort</strong>. The default effort is 65%.</p><h3>02 · Find the connections</h3><p>We check access runs, transfers and the last stretch to your destination. We keep the scheduled vehicle times, include time to board, and respect your total running limit.</p><h3>03 · Follow the whole journey</h3><p>See every run, wait and transit leg on the map. Click a leg for a closer look. Google Maps links open the endpoints; Google will use its own walking times.</p><h3>Fastest found, with an honest limit</h3><p>The live planner searches Google’s returned routes and requests earlier onward connections, with up to 12 route requests per search. It cannot exhaust every possible stop and service. The demo uses a small, illustrative Zürich network.</p>`,
  model: () => `<h2>A pace that fits you.</h2><p>VMA (maximal aerobic speed) is the speed associated with maximal aerobic effort. It is not your everyday running speed.</p><table><thead><tr><th>Starting profile</th><th>VMA</th><th>At 65%</th></tr></thead><tbody><tr><td>Young & athletic</td><td>16 km/h</td><td>10.4 km/h</td></tr><tr><td>Young & less active</td><td>11 km/h</td><td>7.15 km/h</td></tr><tr><td>In your 40s</td><td>12 km/h</td><td>7.8 km/h</td></tr><tr><td>Older adult (65+)</td><td>9 km/h</td><td>5.85 km/h</td></tr></tbody></table><p>These are editable planning examples, not measured averages for these populations. Age and training affect fitness, but age alone cannot determine a person’s VMA. Your own measured VMA is a better starting point.</p><p>The model retains estimated non-moving time for crossings and orientation. Terrain, stairs, crowds and individual fatigue can make a run slower.</p><p>Research context: <a href="https://pubmed.ncbi.nlm.nih.gov/32971113/" target="_blank" rel="noopener">HUNT study on age and aerobic fitness</a> · <a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC9547581/" target="_blank" rel="noopener">Maximal aerobic speed and running economy</a>.</p>`,
  setup: () => `<h2>Your map. Your pace.</h2><div class="setup-state"><i></i>${state.config?.google_available?'Google Routes server key is configured.':'Demo mode is ready. Google Maps is not connected yet.'}</div><h3>Connect live Google Maps journeys</h3><ol><li>In <a href="https://console.cloud.google.com/" target="_blank" rel="noopener">Google Cloud</a>, enable billing, <strong>Routes API</strong> and <strong>Maps JavaScript API</strong>.</li><li>Copy <code>.env.example</code> to <code>.env</code> in the runMap folder. Add a server key and a separate, website-restricted browser key.</li><li>Restart the local server and select <strong>Google Maps</strong> above.</li></ol><pre><code>GOOGLE_MAPS_API_KEY=your_server_key\nGOOGLE_MAPS_BROWSER_KEY=your_browser_key</code></pre><p>Restrict the server key to Routes API and your server IP where practical. Restrict the browser key to Maps JavaScript API and <code>http://127.0.0.1:8787/*</code>. Each search can make up to 12 billable Routes requests.</p><h3>Add the Chrome extension</h3><p>Open <code>chrome://extensions</code>, enable Developer mode, choose <strong>Load unpacked</strong>, and select the <code>extension</code> folder inside runMap. Open a Google Maps journey and choose RunMap.</p><p>The local server must be running. The extension reads the route endpoints and opens this planner.</p>`,
  privacy: () => `<h2>Built for your journey.</h2><h3>What leaves your computer</h3><p>In demo mode, the routing calculation runs locally. The map requests tiles from OpenStreetMap, which receives your IP address and viewed map area. Fonts load from Google Fonts.</p><p>In Google Maps mode, addresses, coordinates and departure times are sent to Google Maps Platform to calculate routes. The browser loads the Google map using a restricted browser key. The server API key is never sent to the browser.</p><h3>Your data</h3><p>RunMap does not store journey history, run analytics or use a user account. Route results stay in memory while the page is open. The extension saves only your planner address in Chrome settings.</p><h3>Using the planner</h3><p>RunMap is an independent local prototype, not affiliated with Google. Running times are estimates, and demo timetables are illustrative. Confirm departures with the transport operator. Google Maps content is subject to <a href="https://www.google.com/help/terms_maps/" target="_blank" rel="noopener">Google Maps terms</a> and <a href="https://policies.google.com/privacy" target="_blank" rel="noopener">Google’s privacy policy</a>.</p>`,
};

function openDialog(type) { $('#dialog-content').innerHTML = dialogs[type](); $('#dialog-eyebrow').textContent = {how:'HOW RUNMAP WORKS',model:'YOUR RUNNING PROFILE',setup:'GET CONNECTED',privacy:'PRIVACY & TERMS'}[type]; $('#info-dialog').showModal(); }

$('#journey-form').addEventListener('submit',event => {event.preventDefault();searchJourney({scroll:true});});
$('#journey-form').addEventListener('input',markStale);
$('#journey-form').addEventListener('change',markStale);
$('#profiles').addEventListener('click',event => {const button=event.target.closest('[data-profile]');if(button){setProfile(button.dataset.profile);markStale();}});
$('#use-location').addEventListener('click',useCurrentLocation);
for (const field of ['origin','destination']) {
  $(`#${field}`).addEventListener('input',()=>{locations[field]=null;if(field==='origin')cancelLocationRequest();});
}
$('#swap').addEventListener('click',()=>{cancelLocationRequest();[$('#origin').value,$('#destination').value]=[$('#destination').value,$('#origin').value];[locations.origin,locations.destination]=[locations.destination,locations.origin];markStale();});
$('#tune-button').addEventListener('click',()=>{const hidden=!$('#tuning').hidden;$('#tuning').hidden=hidden;$('#tune-button').setAttribute('aria-expanded',String(!hidden));});
$('#vma').addEventListener('input',updatePace);
$('#effort').addEventListener('input',updatePace);
$('#departure-mode').addEventListener('change',()=>{$('#date-field').hidden=$('#departure-mode').value==='now';$('#departure-time').required=$('#departure-mode').value==='at';});
function updateSourceMode(showSetup=true) {
  const isGoogle=$('#source-mode').value==='google';
  $('#source-note').innerHTML = `${icon(isGoogle?'info':'beaker')} ${isGoogle?'Uses Google Maps timetables. Running times are estimates.':'Demo journeys use an illustrative timetable.'}`;
  $('#origin').setAttribute('list',isGoogle?'':'places');$('#destination').setAttribute('list',isGoogle?'':'places');
  if (showSetup && isGoogle && !state.config?.google_available) openDialog('setup');
}
$('#source-mode').addEventListener('change',()=>{cancelLocationRequest();updateSourceMode();});
$('#setup-button').addEventListener('click',()=>openDialog('setup'));
$('#map-setup').addEventListener('click',()=>openDialog('setup'));
$('#how-button').addEventListener('click',()=>openDialog('how'));
$('#model-info').addEventListener('click',()=>openDialog('model'));
$('#privacy-button').addEventListener('click',()=>openDialog('privacy'));
$('#plan-tab').addEventListener('click',()=>{$('.sidebar').scrollTo({top:0,behavior:'smooth'});$('#origin').focus();});
$('#close-dialog').addEventListener('click',()=>$('#info-dialog').close());
$('#info-dialog').addEventListener('click',event=>{if(event.target===$('#info-dialog')){const r=$('#info-dialog').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('#info-dialog').close();}});
$('#fit-map').addEventListener('click',fitMap);
$('#zoom-in').addEventListener('click',()=>{if(state.map)state.map.setZoom(state.map.getZoom()+1);});
$('#zoom-out').addEventListener('click',()=>{if(state.map)state.map.setZoom(state.map.getZoom()-1);});

async function init() {
  const now = new Date();now.setMinutes(now.getMinutes()-now.getTimezoneOffset());$('#departure-time').value=now.toISOString().slice(0,16);
  try {
    const response = await fetch('/api/config');
    if (!response.ok) throw new Error('Could not load RunMap settings.');
    state.config = await response.json();
    $('#places').innerHTML = state.config.demo_places.map(place=>`<option value="${escapeHtml(place.name)}"></option>`).join('');
    const params = new URLSearchParams(location.search);
    $('#origin').value = params.get('origin') || state.config.default_origin;
    $('#destination').value = params.get('destination') || state.config.default_destination;
    if (params.has('origin') && state.config.google_available) $('#source-mode').value='google';
    updateSourceMode(false);
    setProfile('young_athletic');
    await ensureMap($('#source-mode').value);
    if (!params.has('origin') || state.config.google_available) await searchJourney();
    else {
      $('#source-mode').value='google';
      $('#source-note').textContent='Imported from Google Maps. Connect your key to plan this journey.';
      openDialog('setup');
    }
  } catch (error) {$('#error').textContent=error.message;$('#error').hidden=false;}
  finally {$('#use-location').disabled=false;}
}
init();
