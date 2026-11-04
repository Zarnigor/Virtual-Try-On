import itemsData from '../mock/items.json';

const STORAGE = {
  token: 'tryon_token',
  user: 'tryon_user',
};

function storageKey(base) {
  const user = getCurrentUser();
  const prefix = user ? user.email : 'guest';
  return `tryon_${prefix}_${base}`;
}

function delay(ms = 120) {
  return new Promise(r => setTimeout(r, ms));
}

function getUsers() {
  try { return JSON.parse(localStorage.getItem('tryon_users') || '[]'); } catch { return []; }
}

function saveUsers(users) {
  localStorage.setItem('tryon_users', JSON.stringify(users));
}

export async function login(email, password) {
  await delay();
  const users = getUsers();
  const user = users.find(u => u.email === email && u.password === password);
  if (!user) throw new Error('Invalid credentials');
  const token = btoa(email + ':' + Date.now());
  localStorage.setItem(STORAGE.token, token);
  localStorage.setItem(STORAGE.user, JSON.stringify({ email: user.email, name: user.name }));
  return { token, user: { email: user.email, name: user.name } };
}

export async function register(name, email, password) {
  await delay();
  const users = getUsers();
  if (users.find(u => u.email === email)) throw new Error('Email already registered');
  users.push({ name, email, password });
  saveUsers(users);
  const token = btoa(email + ':' + Date.now());
  localStorage.setItem(STORAGE.token, token);
  localStorage.setItem(STORAGE.user, JSON.stringify({ email, name }));
  return { token, user: { email, name } };
}

export function logout() {
  localStorage.removeItem(STORAGE.token);
  localStorage.removeItem(STORAGE.user);
}

export function getToken() {
  return localStorage.getItem(STORAGE.token);
}

export function getCurrentUser() {
  try { return JSON.parse(localStorage.getItem(STORAGE.user)); } catch { return null; }
}

export async function getItems() {
  await delay();
  return itemsData;
}

export async function getMeasurements() {
  await delay();
  try {
    return JSON.parse(localStorage.getItem(storageKey('measurements'))) || null;
  } catch { return null; }
}

export async function saveMeasurements(measurements) {
  await delay();
  localStorage.setItem(storageKey('measurements'), JSON.stringify(measurements));
  return measurements;
}

export async function listOutfits() {
  await delay();
  try {
    return JSON.parse(localStorage.getItem(storageKey('outfits'))) || [];
  } catch { return []; }
}

export async function saveOutfit(outfit) {
  await delay();
  const outfits = await listOutfits();
  const existing = outfits.findIndex(o => o.id === outfit.id);
  if (existing >= 0) {
    outfits[existing] = outfit;
  } else {
    outfits.unshift({ ...outfit, id: outfit.id || crypto.randomUUID(), createdAt: new Date().toISOString() });
  }
  localStorage.setItem(storageKey('outfits'), JSON.stringify(outfits));
  return outfits[existing >= 0 ? existing : 0];
}

export async function getOutfit(id) {
  await delay();
  const outfits = await listOutfits();
  return outfits.find(o => o.id === id) || null;
}
