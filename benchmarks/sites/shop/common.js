// Synthetic catalogue shared by the fixture pages. No network access, no real data.
const PRODUCTS = [
  {id: 1, name: 'Red Runner', category: 'shoes', color: 'red', price: 59, stock: true, rating: 4.4},
  {id: 2, name: 'Crimson Trail', category: 'shoes', color: 'red', price: 89, stock: false, rating: 4.7},
  {id: 3, name: 'Blue Runner', category: 'shoes', color: 'blue', price: 55, stock: true, rating: 4.1},
  {id: 4, name: 'Red Rain Jacket', category: 'jackets', color: 'red', price: 120, stock: true, rating: 4.3},
  {id: 5, name: 'Scarlet Sprint', category: 'shoes', color: 'red', price: 72, stock: true, rating: 4.8},
  {id: 6, name: 'Green Hiker', category: 'shoes', color: 'green', price: 99, stock: true, rating: 3.9},
  {id: 7, name: 'Black Parka', category: 'jackets', color: 'black', price: 180, stock: false, rating: 4.6},
  {id: 8, name: 'Red Cap', category: 'hats', color: 'red', price: 19, stock: true, rating: 4.0},
];
const SUGGESTIONS = ['red shoes', 'red jacket', 'red cap', 'blue shoes', 'green shoes', 'black parka'];
function params() { return new URLSearchParams(location.search); }
function cart() { try { return JSON.parse(localStorage.getItem('cart') || '[]'); } catch (_) { return []; } }
function saveCart(items) { localStorage.setItem('cart', JSON.stringify(items)); }
function consentBanner() {
  if (localStorage.getItem('consent')) return;
  const b = document.createElement('div');
  b.id = 'consent';
  b.setAttribute('role', 'dialog');
  b.setAttribute('aria-label', 'Cookie consent');
  b.style.cssText = 'position:fixed;left:0;right:0;top:0;bottom:0;background:rgba(0,0,0,.55);z-index:10;display:flex;align-items:flex-end;justify-content:center';
  b.innerHTML = '<div style="background:#fff;padding:24px;margin:24px;max-width:560px"><p>We use cookies to remember your cart.</p>' +
    '<button id="reject">Reject optional cookies</button> <button id="accept">Accept all cookies</button></div>';
  document.body.appendChild(b);
  b.querySelectorAll('button').forEach(x => x.onclick = () => { localStorage.setItem('consent', x.id); b.remove(); });
}
