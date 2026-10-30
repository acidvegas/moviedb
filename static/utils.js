// Brief message at the bottom of the screen
function toast(message) {
	const el = document.getElementById('toast');
	el.textContent = message;
	el.hidden = false;
	clearTimeout(el._timer);
	el._timer = setTimeout(() => el.hidden = true, 3500);
}

// Remember an on/off UI preference for a year (read server-side by pref())
function remember(name, on) {
	document.cookie = `${name}=${on ? 1 : 0}; path=/; max-age=31536000; samesite=lax`;
}

// Copy text to the clipboard (execCommand, since navigator.clipboard needs HTTPS)
function copyText(text, message) {
	const el = document.createElement('textarea');
	el.value = text;
	document.body.appendChild(el);
	el.select();
	document.execCommand('copy');
	el.remove();
	toast(message);
}

// Replace native selects with a dropdown that opens below the box (some browsers draw the native list on top of it)
function enhanceSelects(root) {
	root.querySelectorAll('select:not([multiple]):not([data-enhanced])').forEach(select => {
		select.dataset.enhanced = '1';
		const wrap = document.createElement('div'), button = document.createElement('button'), list = document.createElement('div');
		wrap.className = 'relative' + (select.classList.contains('w-full') ? ' w-full' : ' inline-block');
		button.type = 'button';
		button.className = select.className + ' flex items-center justify-between gap-2 text-left cursor-pointer';
		list.className = 'absolute left-0 top-full mt-1 z-40 min-w-full max-h-72 overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-900 shadow-2xl py-1 text-sm';
		list.hidden = true;
		const label = () => {
			button.innerHTML = '<span class="truncate"></span><svg class="w-3 h-3 shrink-0 text-zinc-500" fill="currentColor" viewBox="0 0 20 20"><path d="M5 7l5 6 5-6z"/></svg>';
			button.firstChild.textContent = select.options[select.selectedIndex]?.text ?? '';
		};
		const close = () => { list.hidden = true; document.removeEventListener('click', outside); };
		const outside = e => { if (!wrap.contains(e.target)) close(); };
		const choose = option => {
			close();
			if (select.value === option.value) return;
			select.value = option.value;
			label();
			select.dispatchEvent(new Event('change', {bubbles: true}));
		};
		button.addEventListener('click', () => {
			if (!list.hidden) return close();
			list.innerHTML = '';
			for (const child of select.children) {
				for (const option of child.tagName === 'OPTGROUP' ? [child, ...child.children] : [child]) {
					const item = document.createElement('div');
					item.textContent = option.tagName === 'OPTGROUP' ? option.label : option.text;
					if (option.tagName === 'OPTGROUP') item.className = 'px-3 pt-2 pb-1 text-[11px] uppercase tracking-wider text-zinc-500';
					else {
						item.className = 'px-3 py-1.5 whitespace-nowrap cursor-pointer hover:bg-zinc-800 ' + (option.selected ? 'text-accent' : 'text-zinc-200');
						item.addEventListener('click', () => choose(option));
					}
					list.appendChild(item);
				}
			}
			list.hidden = false;
			setTimeout(() => document.addEventListener('click', outside));
		});
		wrap.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
		select.hidden = true;
		select.after(wrap);
		wrap.append(button, list);
		label();
	});
}
document.addEventListener('DOMContentLoaded', () => enhanceSelects(document));
document.addEventListener('htmx:afterSettle', e => enhanceSelects(e.detail.elt));

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
