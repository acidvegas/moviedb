// Brief message at the bottom of the screen
function toast(message) {
	const el = document.getElementById('toast');
	el.textContent = message;
	el.hidden = false;
	clearTimeout(el._timer);
	el._timer = setTimeout(() => el.hidden = true, 3500);
}

// Surface failed htmx requests instead of silently doing nothing
document.addEventListener('htmx:sendError', () => toast("Couldn't reach the server, change not saved"));
document.addEventListener('htmx:responseError', e => toast(e.detail.xhr.status === 503 ? "Server unavailable, change not saved" : `Request failed (${e.detail.xhr.status})`));

// Keyboard shortcuts
let pendingG = false, navIndex = -1;

function navItems() {
	return [...document.querySelectorAll('main [data-nav]')].filter(el => el.offsetParent !== null);
}

function moveNav(step) {
	const items = navItems();
	if (!items.length) return;
	items.forEach(el => el.classList.remove('nav-active'));
	navIndex = Math.max(0, Math.min(items.length - 1, navIndex + step));
	const el = items[navIndex];
	el.classList.add('nav-active');
	el.scrollIntoView({block: 'nearest', behavior: 'smooth'});
}

function clickIn(selector) {
	const el = document.querySelector(selector);
	if (el) el.click();
	return !!el;
}

document.addEventListener('htmx:afterSwap', e => { if (e.detail.target.tagName === 'BODY') { navIndex = -1; } });

document.addEventListener('keydown', e => {
	if (e.ctrlKey || e.metaKey || e.altKey || ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;

	const help = document.getElementById('keys-help');
	if (e.key === 'Escape') { help.hidden = true; return; }

	if (pendingG) {
		pendingG = false;
		const dest = {h: '/', t: '/titles', p: '/names', r: '/recommend', u: '/upcoming', b: '/library', l: '/lists', s: '/settings'}[e.key];
		if (dest) { e.preventDefault(); window.location.href = dest; }
		return;
	}

	const key = e.key, digit = e.code.startsWith('Digit') ? parseInt(e.code.slice(5)) : NaN;

	if (key === '/') { e.preventDefault(); document.getElementById('quick').focus(); }
	else if (key === '?') { help.hidden = !help.hidden; }
	else if (key === 'g') { pendingG = true; setTimeout(() => pendingG = false, 1200); }
	else if (key === 'j' || key === 'ArrowDown' && navIndex >= 0) { e.preventDefault(); moveNav(1); }
	else if (key === 'k' || key === 'ArrowUp' && navIndex >= 0) { e.preventDefault(); moveNav(-1); }
	else if (key === 'Enter' && navIndex >= 0) { const el = navItems()[navIndex]; (el.matches('a') ? el : el.querySelector('a'))?.click(); }
	else if (key === 'w') clickIn('[data-key="watched"]');
	else if (key === 'l') clickIn('[data-key="watchlist"]');
	else if (key === 'f') clickIn('[data-key="follow"]');
	else if (key === 't') clickIn('[data-key="trailer"]');
	else if (digit === 0) clickIn('[data-key="clear-rating"]');
	else if (digit >= 1 && digit <= 5) clickIn(`[data-key="rate-${digit * 2 - (e.shiftKey ? 1 : 0)}"]`);
});
