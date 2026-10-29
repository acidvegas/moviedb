#!/usr/bin/env python3
# MovieDB - developed by acidvegas (https://github.com/acidvegas)

import asyncio
import csv
import functools
import hashlib
import hmac
import io
import json
import math
import os
import random
import re
import secrets
import shutil
import sqlite3
import sys
import time
import zipfile

import xml.etree.ElementTree as ElementTree

from contextlib   import asynccontextmanager
from datetime     import datetime
from html         import unescape
from pathlib      import Path
from urllib.parse import quote, urlencode, urlsplit

try:
	import aiohttp
	import aiosqlite
	from hypercorn.asyncio import serve
	from hypercorn.config  import Config
	from quart             import Quart, abort, g, redirect, render_template, request, Response, send_file
except ImportError:
	raise ImportError('missing dependencies (pip install -r requirements.txt)')

import importer


BASE_DIR     = Path(__file__).resolve().parent
USER_DB      = BASE_DIR / 'user.db'
IMAGE_DIR    = importer.DATA_DIR / 'images'
PAGE_SIZE    = 48
USER_AGENT   = 'MovieDB/1.0'
TITLE_TYPES  = ['movie', 'tvSeries', 'tvMiniSeries', 'tvMovie', 'tvSpecial', 'short', 'tvShort', 'video', 'tvEpisode', 'tvPilot']
GENRES       = ['Action', 'Adventure', 'Animation', 'Biography', 'Comedy', 'Crime', 'Documentary', 'Drama', 'Family', 'Fantasy', 'Film-Noir', 'Game-Show', 'History', 'Horror', 'Music', 'Musical', 'Mystery', 'News', 'Reality-TV', 'Romance', 'Sci-Fi', 'Short', 'Sport', 'Talk-Show', 'Thriller', 'War', 'Western']
TITLE_SORTS  = {'votes': 'votes DESC', 'rating': 'rating DESC, votes DESC', 'newest': 'start_year DESC, votes DESC', 'oldest': 'start_year ASC, votes DESC', 'title': 'primary_title COLLATE NOCASE', 'mine': "(SELECT rating FROM u.ratings WHERE user_id = {uid} AND kind = 'tt' AND id = tconst) DESC, votes DESC"}
MINE_FILTERS = {'watched': "tconst IN (SELECT tconst FROM u.marks WHERE user_id = {uid} AND mark = 'watched')", 'unwatched': "tconst NOT IN (SELECT tconst FROM u.marks WHERE user_id = {uid} AND mark = 'watched')", 'watchlist': "tconst IN (SELECT tconst FROM u.marks WHERE user_id = {uid} AND mark = 'watchlist')", 'rated': "tconst IN (SELECT id FROM u.ratings WHERE user_id = {uid} AND kind = 'tt')"}
LB_TYPES     = ('movie', 'tvMovie', 'video', 'short', 'tvShort', 'tvSpecial', 'tvMiniSeries', 'tvSeries')
REC_TYPES    = ('movie', 'tvMovie', 'tvSeries', 'tvMiniSeries')
NAME_SORTS   = {'score': 'score DESC', 'credits': 'credits DESC', 'name': 'name COLLATE NOCASE', 'born': 'birth_year DESC'}
TMDB_TTL     = {'tv': 86400, 'movie': 30 * 86400, 'episode': 30 * 86400, 'person': 30 * 86400}
TMDB_RATE    = 35
IMG_SIZES    = ('w92', 'w185', 'w342', 'w500', 'w780', 'w1280', 'original')
PRECACHE     = {'titles': 50_000, 'people': 20_000, 'workers': 12}
SUBS_DIR     = importer.DATA_DIR / 'subs'
OS_AGENT     = 'MovieDB v1.0'
WEEK         = 7 * 86400
SESSION_AGE  = 365 * 86400
CAPTCHA      = {'A': '0,12 4,0 8,12;1.5,7.5 6.5,7.5', 'C': '8,1.5 6,0 2,0 0,3 0,9 2,12 6,12 8,10.5', 'D': '0,0 0,12 5,12 8,9 8,3 5,0 0,0', 'E': '8,0 0,0 0,12 8,12;0,6 6,6', 'F': '8,0 0,0 0,12;0,6 6,6', 'G': '8,1.5 6,0 2,0 0,3 0,9 2,12 6,12 8,10 8,7 5,7', 'H': '0,0 0,12;8,0 8,12;0,6 8,6', 'J': '8,0 8,9 6,12 2,12 0,9', 'K': '0,0 0,12;8,0 0,7;3,5 8,12', 'M': '0,12 0,0 4,7 8,0 8,12', 'N': '0,12 0,0 8,12 8,0', 'P': '0,12 0,0 6,0 8,2 8,4 6,6 0,6', 'R': '0,12 0,0 6,0 8,2 8,4 6,6 0,6;4,6 8,12', 'T': '0,0 8,0;4,0 4,12', 'U': '0,0 0,9 2,12 6,12 8,9 8,0', 'V': '0,0 4,12 8,0', 'W': '0,0 2,12 4,5 6,12 8,0', 'X': '0,0 8,12;8,0 0,12', 'Y': '0,0 4,6 8,0;4,6 4,12', '3': '0,1 2,0 6,0 8,2 8,4 6,6 3,6;6,6 8,8 8,10 6,12 2,12 0,11', '4': '6,12 6,0 0,8 8,8', '6': '7,0 3,0 0,4 0,10 2,12 6,12 8,10 8,8 6,6 2,6 0,8', '7': '0,0 8,0 3,12', '9': '8,4 6,6 2,6 0,4 0,2 2,0 6,0 8,2 8,8 5,12 1,12'}
STREAM_SITES = [
	('1Shows',       'https://www.1shows.org',         '/movies/{tmdb}',               '/tv/{tmdb}',               None),
	('321Movies',    'https://321movies.co.uk',        '/movie/{tmdb}',                '/tv/{tmdb}',               None),
	('67movies',     'https://67movies.st',            '/details/movie/{tmdb}',        '/details/tv/{tmdb}',       None),
	('7reels',       'https://7reels.cc',              None,                           None,                       '/search?q={q}'),
	('ApexMovies',   'https://apexmovies.net',         None,                           None,                       '/?s={q}'),
	('Bcine',        'https://freekz.to',              '/movie/{tmdb}',                '/tv/{tmdb}',               None),
	('Bingeflix',    'https://bingeflix.tv',           '/movie/{tmdb}/details',        '/tv/{tmdb}/details',       '/search?q={q}'),
	('Cinecat',      'https://cinecat.eu',             '/media/tmdb-movie-{tmdb}',     '/media/tmdb-tv-{tmdb}',    None),
	('Cinejoy',      'https://cinejoy.pk',             '/watch/movie/{tmdb}',          '/watch/tv/{tmdb}/1/1',     '/search/{q}'),
	('Cinema.army',  'https://cinema.army',            None,                           None,                       '/search?q={q}'),
	('CineWave',     'https://watch.cinewave.qzz.io',  '/details/movie/{tmdb}',        '/details/tv/{tmdb}',       None),
	('Cinezo',       'https://cinezo.st',              '/movie/{tmdb}',                '/tv/{tmdb}',               None),
	('CornClick',    'https://cornclick.com',          None,                           None,                       '/search?q={q}'),
	('Donkey',       'https://donkey.to',              None,                           None,                       '/media/search?query={q}'),
	('Filmex',       'https://filmex.to',              '/movie/{tmdb}',                '/tv/{tmdb}',               None),
	('FshareTV',     'https://fsharetv.co',            '/movie/{imdb}',                None,                       '/search?q={q}'),
	('Koddo',        'https://koddo.to',               None,                           None,                       '/en/search?q={q}'),
	('LatestMovies', 'https://latestmovies.net',       '/movie/{tmdb}',                '/tv/{tmdb}',               None),
	('LookMovie',    'https://www.lookmovie2.to',      '/movies/search/?q={q}',        '/shows/search/?q={q}',     None),
	('M-Zone',       'https://m-zone.cc',              '/details/movie/{tmdb}',        '/details/tv/{tmdb}',       None),
	('Mapple',       'https://mapple.fun',             '/movie/{tmdb}',                '/tv/{tmdb}',               None),
	('Movish',       'https://movish.to',              None,                           None,                       '/search/{q}'),
	('PressPlay',    'https://pressplayz.top',         '/watch/movie/{tmdb}',          '/watch/tv/{tmdb}',         None),
	('Redflix',      'https://redflix.one',            '/play?id={tmdb}&type=movie',   None,                       None),
	('Reelix',       'https://reelix.ac',              None,                           None,                       '/search/{q}'),
	('Screenopps',   'https://screenopps.com',         '/details/movie/{tmdb}/1',      '/details/tv/{tmdb}/1',     None),
	('Shiopa',       'https://shiopa.com',             '/watch/{tmdb}?type=movie',     '/watch/{tmdb}?type=tv',    None),
	('Smashystream', 'https://smashystream.xyz',       '/movie/{tmdb}',                '/tv/{tmdb}',               None)
]
PLACEHOLDER  = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 3"><rect width="2" height="3" fill="#27272a"/></svg>'
NO_COVER     = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300"><defs><linearGradient id="g" x2="0" y2="1"><stop offset="0" stop-color="#27272a"/><stop offset="1" stop-color="#18181b"/></linearGradient></defs><rect width="200" height="300" fill="url(#g)"/><g fill="none" stroke="#52525b" stroke-width="5" stroke-linejoin="round"><rect x="66" y="106" width="68" height="56" rx="7"/><path d="M84 106v56M116 106v56M66 125h18M66 143h18M116 125h18M116 143h18"/></g><text x="100" y="198" fill="#71717a" font-family="Inter,system-ui,sans-serif" font-size="17" font-weight="600" text-anchor="middle">No cover</text></svg>'
NO_PHOTO     = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300"><defs><linearGradient id="g" x2="0" y2="1"><stop offset="0" stop-color="#27272a"/><stop offset="1" stop-color="#18181b"/></linearGradient></defs><rect width="200" height="300" fill="url(#g)"/><g fill="#3f3f46"><circle cx="100" cy="122" r="34"/><path d="M38 220c0-38 28-58 62-58s62 20 62 58z"/></g></svg>'
USER_SCHEMA  = '''
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS users           (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, password TEXT, admin INTEGER DEFAULT 0, approved INTEGER DEFAULT 0, created REAL);
CREATE TABLE IF NOT EXISTS sessions        (token TEXT PRIMARY KEY, user_id INTEGER, expires REAL);
CREATE TABLE IF NOT EXISTS user_settings   (user_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (user_id, key));
CREATE TABLE IF NOT EXISTS subtitle_keys   (user_id INTEGER PRIMARY KEY, subdl_key TEXT DEFAULT '', os_key TEXT DEFAULT '', os_user TEXT DEFAULT '', os_pass TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS lists           (id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '', created REAL, updated REAL, user_id INTEGER);
CREATE TABLE IF NOT EXISTS list_items      (list_id INTEGER REFERENCES lists(id) ON DELETE CASCADE, tconst INTEGER, added REAL, PRIMARY KEY (list_id, tconst));
CREATE TABLE IF NOT EXISTS settings        (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS posters         (id TEXT PRIMARY KEY, url TEXT, source TEXT, fetched REAL);
CREATE TABLE IF NOT EXISTS tmdb            (id TEXT PRIMARY KEY, data TEXT, fetched REAL);
CREATE TABLE IF NOT EXISTS tmdb_ids        (kind TEXT, tmdb_id INTEGER, imdb_id TEXT, PRIMARY KEY (kind, tmdb_id));
CREATE TABLE IF NOT EXISTS title_providers (tconst INTEGER, provider_id INTEGER, PRIMARY KEY (tconst, provider_id));
CREATE TABLE IF NOT EXISTS ratings         (user_id INTEGER, kind TEXT, id INTEGER, rating INTEGER, updated REAL, PRIMARY KEY (user_id, kind, id));
CREATE TABLE IF NOT EXISTS marks           (user_id INTEGER, tconst INTEGER, mark TEXT, added REAL, PRIMARY KEY (user_id, tconst, mark));
CREATE TABLE IF NOT EXISTS follows         (user_id INTEGER, nconst INTEGER, added REAL, PRIMARY KEY (user_id, nconst));
CREATE TABLE IF NOT EXISTS lb_map          (slug TEXT PRIMARY KEY, tconst INTEGER);
CREATE TABLE IF NOT EXISTS lb_unmatched    (user_id INTEGER, key TEXT, name TEXT, sections TEXT, rating INTEGER, PRIMARY KEY (user_id, key));
CREATE TABLE IF NOT EXISTS subtitles       (tconst INTEGER PRIMARY KEY, data TEXT, fetched REAL);
'''

app        = Quart(__name__, static_folder='static', template_folder='templates')
state      = {'session': None, 'update': None, 'lb': {}, 'precache': {}, 'subs': {}, 'images': None, 'images_at': 0.0, 'tmdb_last': 0.0, 'tmdb_lock': None, 'os_tokens': {}, 'captchas': {}}
poster_sem = asyncio.Semaphore(4)
tasks      = set()


def captcha_new() -> str:
	'''Create a register captcha (6 random characters, valid for 10 minutes) and return its id.'''

	now = time.time()

	for key in [key for key, (_, expires) in state['captchas'].items() if expires < now or len(state['captchas']) > 5000]:
		del state['captchas'][key]

	token = secrets.token_urlsafe(16)
	state['captchas'][token] = (''.join(secrets.choice(list(CAPTCHA)) for _ in range(6)), now + 600)

	return token


def captcha_svg(text: str) -> str:
	'''
	Draw captcha text as distorted line strokes: every glyph is jittered, scaled, rotated, sheared and waved, over noise curves. The text itself never appears in the SVG.

	:param text: Characters to draw (keys of CAPTCHA)
	'''

	width, height = 300, 90
	colors        = ('#f5c518', '#e4e4e7', '#a1a1aa', '#fbbf24', '#d4d4d8')
	wave          = (random.uniform(3, 6), random.uniform(18, 30), random.uniform(0, math.tau))
	parts         = [f'<rect width="{width}" height="{height}" rx="10" fill="#18181b"/>']

	def curve(color: str, stroke: float) -> str:
		points = [(random.uniform(-10, width / 3), random.uniform(0, height)), (random.uniform(0, width), random.uniform(0, height)), (random.uniform(0, width), random.uniform(0, height)), (random.uniform(width * 2 / 3, width + 10), random.uniform(0, height))]
		return f'<path d="M{points[0][0]:.1f} {points[0][1]:.1f}C' + ' '.join(f'{x:.1f} {y:.1f}' for x, y in points[1:]) + f'" fill="none" stroke="{color}" stroke-width="{stroke:.1f}" opacity="{random.uniform(0.4, 0.9):.2f}"/>'

	parts += [curve(random.choice(('#3f3f46', '#52525b', '#71717a')), random.uniform(1, 2.5)) for _ in range(7)]
	parts += [f'<circle cx="{random.uniform(0, width):.1f}" cy="{random.uniform(0, height):.1f}" r="{random.uniform(0.6, 1.8):.1f}" fill="#71717a"/>' for _ in range(45)]
	x = random.uniform(14, 30)

	for char in text:
		scale  = random.uniform(3.4, 4.0)
		angle  = random.uniform(-0.3, 0.3)
		shear  = random.uniform(-0.25, 0.25)
		cx, cy = x + 4 * scale, height / 2 + random.uniform(-6, 6)
		color  = random.choice(colors)
		paths  = []
		for stroke in CAPTCHA[char].split(';'):
			points = []
			for point in stroke.split():
				gx, gy = (float(v) + random.uniform(-0.45, 0.45) for v in point.split(','))
				dx, dy = (gx - 4) * scale, (gy - 6) * scale
				dx    += shear * dy
				px, py = cx + dx * math.cos(angle) - dy * math.sin(angle), cy + dx * math.sin(angle) + dy * math.cos(angle)
				points.append(f'{px:.1f} {py + wave[0] * math.sin(px / wave[1] + wave[2]):.1f}')
			paths.append('M' + 'L'.join(points))
		parts.append(f'<path d="{"".join(paths)}" fill="none" stroke="{color}" stroke-width="{random.uniform(2.6, 3.6):.1f}" stroke-linecap="round" stroke-linejoin="round"/>')
		x += 8 * scale * random.uniform(0.95, 1.1)

	parts += [curve(random.choice(colors), random.uniform(1.2, 2)) for _ in range(2)]

	return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">{"".join(parts)}</svg>'


async def delete_user(user_id: int):
	'''
	Delete an account and everything it owns.

	:param user_id: Account id
	'''

	async with user_db() as db:
		await db.execute('DELETE FROM list_items WHERE list_id IN (SELECT id FROM lists WHERE user_id = ?)', (user_id,))
		for table in ('lists', 'ratings', 'marks', 'follows', 'lb_unmatched', 'user_settings', 'subtitle_keys', 'sessions'):
			await db.execute(f'DELETE FROM {table} WHERE user_id = ?', (user_id,))
		await db.execute('DELETE FROM users WHERE id = ?', (user_id,))
		await db.commit()

	state['lb'].pop(user_id, None)
	state['os_tokens'].pop(f'os:{user_id}', None)


async def download(url: str, path: Path) -> bool:
	'''
	Download a URL to a file atomically.

	:param url: Source URL
	:param path: Destination path
	'''

	try:
		async with state['session'].get(url, headers={'User-Agent': USER_AGENT}) as response:
			if response.status != 200:
				return False
			body = await response.read()
	except (aiohttp.ClientError, asyncio.TimeoutError):
		return False

	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix('.part')
	tmp.write_bytes(body)
	tmp.replace(path)

	return True


async def ensure_poster(imdb_id: str, letterboxd: bool = True) -> Path | None:
	'''
	Return the local poster/headshot file for an IMDb id, downloading it first if needed.

	:param imdb_id: IMDb id (tt... or nm...)
	:param letterboxd: Allow the Letterboxd fallback for titles without a TMDB poster
	'''

	path = IMAGE_DIR / 'poster' / f'{imdb_id}.jpg'

	if path.exists():
		return path

	async with user_db() as db:
		rows = await db.execute_fetchall('SELECT url, fetched FROM posters WHERE id = ?', (imdb_id,))

	if rows and not rows[0]['url'] and time.time() - rows[0]['fetched'] < WEEK:
		return None

	url, source = (rows[0]['url'], None) if rows and rows[0]['url'] else (None, None)

	if not url and (data := await tmdb_details(imdb_id, cached_only=True)) and (image := data.get('poster_path') or data.get('profile_path')):
		url, source = f'https://image.tmdb.org/t/p/w342{image}', 'tmdb'

	if not url:
		key = await setting('tmdb_key')
		async with poster_sem:
			try:
				if key:
					url, source = await fetch_tmdb(imdb_id, key), 'tmdb'
				if not url and letterboxd and imdb_id.startswith('tt'):
					url, source = await fetch_letterboxd(imdb_id), 'letterboxd'
			except (aiohttp.ClientError, asyncio.TimeoutError):
				return None

	if (url and source) or (not url and letterboxd):
		async with user_db() as db:
			await db.execute('INSERT OR REPLACE INTO posters VALUES (?, ?, ?, ?)', (imdb_id, url, source if url else None, time.time()))
			await db.commit()

	return path if url and await download(url, path) else None


async def fetch_letterboxd(tconst: str) -> str | None:
	'''
	Find a poster URL for a title via Letterboxd's IMDb redirect.

	:param tconst: IMDb title id (tt...)
	'''

	async with state['session'].get(f'https://letterboxd.com/imdb/{tconst}/', headers={'User-Agent': USER_AGENT}) as response:
		if response.status != 200 or '/film/' not in str(response.url):
			return None
		match = re.search(r'"image":"([^"]+)"', await response.text())

	return match.group(1) if match else None


async def fetch_tmdb(imdb_id: str, key: str) -> str | None:
	'''
	Find a poster or profile image URL on TMDB by IMDb id.

	:param imdb_id: IMDb id (tt... or nm...)
	:param key: TMDB v3 API key or v4 read access token
	'''

	data = await tmdb_request(f'find/{imdb_id}', key, {'external_source': 'imdb_id'}) or {}

	for group, field in (('movie_results', 'poster_path'), ('tv_results', 'poster_path'), ('tv_episode_results', 'still_path'), ('person_results', 'profile_path')):
		for item in data.get(group, []):
			if item.get(field):
				return f'https://image.tmdb.org/t/p/w342{item[field]}'

	return None


def fmt_id(prefix: str, value: int) -> str:
	'''
	Format an integer id back to an IMDb identifier.

	:param prefix: 'tt' or 'nm'
	:param value: Numeric id
	'''

	return f'{prefix}{value:07d}'


def fts_query(text: str) -> str:
	'''
	Convert free text to an FTS5 prefix query, keeping punctuated words like V/H/S as one phrase.

	:param text: User search text
	'''

	return ' '.join(f'"{" ".join(tokens)}"*' for word in text.split() if (tokens := re.findall(r'\w+', word)))


async def image_usage():
	'''Total the size of the image cache in a thread, so walking tens of thousands of files never blocks requests.'''

	state['images'] = await asyncio.to_thread(lambda: sum(f.stat().st_size for f in IMAGE_DIR.rglob('*') if f.is_file()) if IMAGE_DIR.exists() else 0)


async def imdb_db() -> aiosqlite.Connection:
	'''Open a read-only connection to the IMDb database, aborting if it has not been built.'''

	if not importer.DB_PATH.exists():
		abort(503)

	db = await aiosqlite.connect(f'file:{importer.DB_PATH}?mode=ro', uri=True)
	db.row_factory = aiosqlite.Row
	await db.execute(f"ATTACH DATABASE 'file:{USER_DB}?mode=ro' AS u")

	return db


async def lb_status() -> str:
	'''Render the Letterboxd sync status partial.'''

	async with user_db() as db:
		unmatched = (await db.execute_fetchall('SELECT count(*) AS n FROM lb_unmatched WHERE user_id = ?', (g.user['id'],)))[0]['n']

	return await render_template('_lb_status.html', lb=state['lb'].get(g.user['id'], {}), result=json.loads(await user_setting('lb_result', '{}')), unmatched=unmatched)


async def letterboxd_apply(user_id: int, source: str, watched: list, watchlist: list, rated: list, mirror_watched: bool):
	'''
	Match Letterboxd items to IMDb and write them to an account's marks and ratings.

	:param user_id: Account id
	:param source: 'export' or 'sync', recorded in the result
	:param watched: List of (key, name, rating) watched films
	:param watchlist: List of (key, name, rating) watchlist films
	:param rated: List of (key, name, rating) rated films
	:param mirror_watched: Replace all watched marks instead of adding to them
	'''

	mapping   = await letterboxd_match(user_id, watched + watchlist + rated)
	now       = time.time()
	ratings   = [(user_id, 'tt', mapping[key], rating, now) for key, _, rating in rated if rating and mapping.get(key)]
	unmatched = {}

	for section, items in (('watched', watched), ('watchlist', watchlist), ('rated', rated)):
		for key, name, rating in items:
			if not mapping.get(key):
				entry = unmatched.setdefault(key, [name, set(), None])
				entry[1].add(section)
				entry[2] = rating or entry[2]

	async with user_db() as db:
		await db.execute("DELETE FROM marks WHERE user_id = ? AND (mark = 'watchlist'" + (" OR mark = 'watched')" if mirror_watched else ')'), (user_id,))
		await db.executemany('INSERT OR IGNORE INTO marks VALUES (?, ?, ?, ?)', [(user_id, mapping[key], 'watched', now) for key, _, _ in watched if mapping.get(key)])
		await db.executemany('INSERT OR IGNORE INTO marks VALUES (?, ?, ?, ?)', [(user_id, mapping[key], 'watchlist', now) for key, _, _ in watchlist if mapping.get(key)])
		cursor = await db.executemany('INSERT OR IGNORE INTO ratings VALUES (?, ?, ?, ?, ?)', ratings)
		if source == 'export':
			await db.execute('DELETE FROM lb_unmatched WHERE user_id = ?', (user_id,))
		await db.executemany('INSERT OR REPLACE INTO lb_unmatched VALUES (?, ?, ?, ?, ?)', [(user_id, key, name, ','.join(sorted(sections)), rating) for key, (name, sections, rating) in unmatched.items()])
		result = {'time': now, 'source': source, 'user': await user_setting('letterboxd_user', user_id=user_id), 'watched': len(watched), 'watchlist': len(watchlist), 'ratings': len(ratings), 'new_ratings': cursor.rowcount}
		await db.executemany('INSERT OR REPLACE INTO user_settings VALUES (?, ?, ?)', [(user_id, 'lb_last_sync', str(now)), (user_id, 'lb_result', json.dumps(result))] + ([(user_id, 'lb_last_export', str(now))] if source == 'export' else []))
		await db.commit()


async def letterboxd_import(user_id: int, data: bytes):
	'''
	Import a Letterboxd data export zip: full mirror of watched and watchlist, ratings added without overwriting local ones.

	:param user_id: Account id
	:param data: Raw zip file bytes
	'''

	state['lb'][user_id] = {'running': True, 'step': 'Reading export', 'progress': '', 'error': None}

	try:
		with zipfile.ZipFile(io.BytesIO(data)) as archive:
			def read(name: str) -> list:
				if name not in archive.namelist():
					raise RuntimeError(f'{name} not found in export zip')
				rows = csv.DictReader(io.TextIOWrapper(archive.open(name), encoding='utf-8'))
				return [(row['Letterboxd URI'], f"{row['Name']} ({row['Year']})" if row.get('Year') else row['Name'], round(float(row['Rating']) * 2) if row.get('Rating') else None) for row in rows]

			watched, watchlist, rated = read('watched.csv'), read('watchlist.csv'), read('ratings.csv')

		await letterboxd_apply(user_id, 'export', watched, watchlist, rated, True)
		state['lb'][user_id] = {'running': False}
	except Exception as e:
		state['lb'][user_id] = {'running': False, 'error': f'{type(e).__name__}: {e}'}


async def letterboxd_match(user_id: int, items: list) -> dict:
	'''
	Map Letterboxd film slugs to IMDb tconsts, using the cache, then an exact local title+year match, then the film page's IMDb link.

	:param user_id: Account id, for progress reporting
	:param items: List of (slug, name, rating) tuples
	'''

	async with user_db() as db:
		mapping = {row['slug']: row['tconst'] for row in await db.execute_fetchall('SELECT slug, tconst FROM lb_map')}

	todo  = list(dict.fromkeys((slug, name) for slug, name, _ in items if slug not in mapping))
	found = {}
	fetch = []

	for slug, name in todo:
		match = re.match(r'^(.*) \((\d{4})\)$', name)
		if match and (tconst := await match_title(match.group(1), int(match.group(2)), LB_TYPES, exact_year=True)):
			found[slug] = tconst
			continue
		fetch.append(slug)

	sem = asyncio.Semaphore(4)

	async def lookup(slug: str):
		async with sem:
			try:
				async with state['session'].get(slug if slug.startswith('http') else f'https://letterboxd.com/film/{slug}/', headers={'User-Agent': USER_AGENT}) as response:
					match = re.search(r'imdb\.com/title/tt(\d+)', await response.text()) if response.status == 200 else None
			except (aiohttp.ClientError, asyncio.TimeoutError):
				return
		found[slug] = int(match.group(1)) if match else None
		state['lb'][user_id]['progress'] = f'{len(found):,} / {len(todo):,} matched'

	state['lb'][user_id]['step'] = f'Matching {len(todo):,} new films ({len(fetch):,} need a page lookup)'
	await asyncio.gather(*(lookup(slug) for slug in fetch))

	async with user_db() as db:
		await db.executemany('INSERT OR REPLACE INTO lb_map VALUES (?, ?)', found.items())
		await db.commit()

	return mapping | found


async def letterboxd_scrape(user_id: int, user: str, section: str, max_pages: int = 10_000) -> list:
	'''
	Scrape the pages of a Letterboxd user's films or watchlist.

	:param user_id: Account id, for progress reporting
	:param user: Letterboxd username
	:param section: 'films' (watched) or 'watchlist'
	:param max_pages: Stop after this many pages
	'''

	items = []
	page  = 1
	last  = 1

	while page <= last:
		state['lb'][user_id]['step'] = f'Scraping {section} page {page} / {last}'

		async with state['session'].get(f'https://letterboxd.com/{user}/{section}/' + (f'page/{page}/' if page > 1 else ''), headers={'User-Agent': USER_AGENT}) as response:
			if response.status != 200:
				raise RuntimeError(f'letterboxd returned HTTP {response.status} for {section} page {page}')
			html = await response.text()

		last = min(max_pages, max([last] + [int(n) for n in re.findall(rf'/{section}/page/(\d+)/', html)]))

		for item in html.split('<li class="griditem">')[1:]:
			slug   = re.search(r'data-item-slug="([^"]+)"', item)
			name   = re.search(r'data-item-name="([^"]+)"', item)
			rating = re.search(r'rated-(\d+)', item)
			if slug:
				items.append((slug.group(1), unescape(name.group(1)) if name else '', int(rating.group(1)) if rating else None))

		page += 1
		await asyncio.sleep(0.5)

	return items


async def letterboxd_sync(user_id: int):
	'''
	Daily sync: mirror the Letterboxd watchlist, and add the latest watched films and ratings (only page 1 is reachable without login).

	:param user_id: Account id
	'''

	user                 = await user_setting('letterboxd_user', user_id=user_id)
	state['lb'][user_id] = {'running': True, 'step': 'Starting', 'progress': '', 'error': None}

	try:
		watched   = await letterboxd_scrape(user_id, user, 'films', 1)
		watchlist = await letterboxd_scrape(user_id, user, 'watchlist')
		if not watched and not watchlist:
			raise RuntimeError(f'no films found for {user} (private profile or wrong username?)')

		await letterboxd_apply(user_id, 'sync', watched, watchlist, watched, False)
		state['lb'][user_id] = {'running': False}
	except Exception as e:
		state['lb'][user_id] = {'running': False, 'error': f'{type(e).__name__}: {e}'}


async def list_summaries() -> list:
	'''Return the logged-in account's lists with their item counts.'''

	async with user_db() as db:
		return await db.execute_fetchall('SELECT l.*, count(i.tconst) AS count FROM lists l LEFT JOIN list_items i ON i.list_id = l.id WHERE l.user_id = ? GROUP BY l.id ORDER BY l.updated DESC', (g.user['id'],))


def load_env():
	'''Load KEY=VALUE pairs from .env into the environment without overriding existing variables.'''

	path = BASE_DIR / '.env'

	if path.exists():
		for line in path.read_text().splitlines():
			if '=' in line and not line.lstrip().startswith('#'):
				key, value = line.split('=', 1)
				os.environ.setdefault(key.strip(), value.strip().strip('\'"'))


async def match_title(name: str, year: int | None, types: tuple, exact_year: bool = False) -> int | None:
	'''
	Find the tconst for a title name and year, preferring an unambiguous exact match.

	:param name: Title
	:param year: Release year
	:param types: Allowed title types
	:param exact_year: Require the exact year and a single match (otherwise allow +/- 1 year and take the most voted)
	'''

	if not (phrase := ' '.join(re.findall(r'\w+', name))) or not year:
		return None

	years = (year,) if exact_year else (year - 1, year, year + 1)

	for table in ('titles_pop_fts', 'titles_fts'):
		rows = await query(f'SELECT DISTINCT t.tconst FROM {table} f JOIN titles t ON t.tconst = f.rowid WHERE {table} MATCH ? AND t.start_year IN ({",".join("?" * len(years))}) AND t.type IN ({",".join("?" * len(types))}) AND (lower(t.primary_title) = lower(?) OR lower(t.original_title) = lower(?)) ORDER BY t.votes DESC', (f'"{phrase}"', *years, *types, name, name))
		if rows and (len(rows) == 1 or not exact_year):
			return rows[0]['tconst']

	return None


async def migrate_users(db: aiosqlite.Connection):
	'''
	Give the data from before accounts existed to the admin account (id 1). Runs once; old tables are renamed to *_old before USER_SCHEMA creates the new ones.

	:param db: Open user database connection
	'''

	old = [row['name'] for row in await db.execute_fetchall("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '%_old'")]

	for table, columns in (('ratings', 'kind, id, rating, updated'), ('marks', 'tconst, mark, added'), ('follows', 'nconst, added'), ('lb_unmatched', 'key, name, sections, rating')):
		if f'{table}_old' in old:
			await db.execute(f'INSERT OR IGNORE INTO {table} (user_id, {columns}) SELECT 1, {columns} FROM {table}_old')
			await db.execute(f'DROP TABLE {table}_old')

	if 'user_id' not in [row['name'] for row in await db.execute_fetchall('PRAGMA table_info(lists)')]:
		await db.execute('ALTER TABLE lists ADD COLUMN user_id INTEGER')
		await db.execute('UPDATE lists SET user_id = 1')

	for key in ('letterboxd_user', 'providers', 'lb_last_sync', 'lb_result', 'lb_last_export'):
		await db.execute('INSERT OR IGNORE INTO user_settings SELECT 1, key, value FROM settings WHERE key = ?', (key,))
		await db.execute('DELETE FROM settings WHERE key = ?', (key,))

	if (rows := await db.execute_fetchall("SELECT key, value FROM settings WHERE key IN ('subdl_key', 'os_key', 'os_user', 'os_pass')")):
		keys = {row['key']: row['value'] for row in rows}
		await db.execute('INSERT OR REPLACE INTO subtitle_keys VALUES (1, ?, ?, ?, ?)', tuple(keys.get(k, '') for k in ('subdl_key', 'os_key', 'os_user', 'os_pass')))
		await db.execute("DELETE FROM settings WHERE key IN ('subdl_key', 'os_key', 'os_user', 'os_pass')")


async def my_providers() -> list:
	'''Return the logged-in account's selected streaming provider ids (none for guests).'''

	return json.loads(await user_setting('providers', '[]')) if g.user else []


async def opensubtitles_request(account: dict, method: str, path: str, auth: bool = False, **kwargs) -> dict:
	'''
	Make an OpenSubtitles API request with one pooled key, logging in first when auth is needed and the key has a login. Raises RuntimeError on failure.

	:param account: Pooled OpenSubtitles key from subtitle_accounts()
	:param method: HTTP method
	:param path: API path after /api/v1/
	:param auth: Send the login token (raises the daily download limit from 5 to the account's limit)
	'''

	headers = {'Api-Key': account['key'], 'User-Agent': OS_AGENT, 'Accept': 'application/json'}
	tokens  = state['os_tokens']

	if auth and account['user']:
		if account['id'] not in tokens:
			login = await opensubtitles_request(account, 'POST', 'login', json={'username': account['user'], 'password': account['pass']})
			tokens[account['id']] = (login['token'], login.get('base_url') or 'api.opensubtitles.com')
		headers['Authorization'] = f'Bearer {tokens[account["id"]][0]}'

	try:
		async with state['session'].request(method, f'https://{tokens[account["id"]][1] if account["id"] in tokens else "api.opensubtitles.com"}/api/v1/{path}', headers=headers, **kwargs) as response:
			data = await response.json(content_type=None)
	except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
		raise RuntimeError(f'{type(e).__name__}: {e}') from e

	if response.status == 401 and auth and tokens.pop(account['id'], None):
		return await opensubtitles_request(account, method, path, auth, **kwargs)

	if response.status != 200:
		raise RuntimeError(str(data.get('message') or data.get('errors') or f'HTTP {response.status}') if isinstance(data, dict) else f'HTTP {response.status}')

	return data


def password_check(password: str, stored: str | None) -> bool:
	'''
	Check a password against a stored scrypt hash.

	:param password: Password to check
	:param stored: Hash from password_hash()
	'''

	try:
		_, salt, digest = stored.split('$')
	except (AttributeError, ValueError):
		return False

	return hmac.compare_digest(hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex(), digest)


def password_hash(password: str) -> str:
	'''
	Hash a password with scrypt and a random salt.

	:param password: Password to hash
	'''

	salt = secrets.token_bytes(16)

	return f'scrypt${salt.hex()}${hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()}'


async def precache():
	'''Pre-download TMDB details and posters for the library plus the most popular titles and people.'''

	state['precache'] = {'running': True, 'step': 'Collecting ids', 'done': 0, 'total': 0, 'error': None}

	try:
		async with user_db() as db:
			library  = [fmt_id('tt', r[0]) for r in await db.execute_fetchall('SELECT tconst FROM marks UNION SELECT tconst FROM list_items UNION SELECT id FROM ratings WHERE kind = \'tt\'')]
			library += [fmt_id('nm', r[0]) for r in await db.execute_fetchall('SELECT nconst FROM follows UNION SELECT id FROM ratings WHERE kind = \'nm\'')]

		top_titles = [fmt_id('tt', r['tconst']) for r in await query("SELECT tconst FROM titles WHERE type != 'tvEpisode' ORDER BY votes DESC LIMIT ?", (PRECACHE['titles'],))]
		top_people = [fmt_id('nm', r['nconst']) for r in await query('SELECT nconst FROM names ORDER BY score DESC LIMIT ?', (PRECACHE['people'],))]
		ids        = list(dict.fromkeys(library + top_titles + top_people))
		queue      = asyncio.Queue()

		for imdb_id in ids:
			queue.put_nowait(imdb_id)

		state['precache'] |= {'step': f'Caching {len(library):,} library items, {len(top_titles):,} titles, {len(top_people):,} people', 'total': len(ids)}

		async def worker():
			while not queue.empty():
				imdb_id = queue.get_nowait()
				await tmdb_details(imdb_id)
				await ensure_poster(imdb_id, letterboxd=False)
				state['precache']['done'] += 1

		await asyncio.gather(*(worker() for _ in range(PRECACHE['workers'])))

		async with user_db() as db:
			await db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', ('precache_last', str(time.time())))
			await db.commit()

		state['precache'] = {'running': False, 'last': time.time()}
	except Exception as e:
		state['precache'] = {'running': False, 'error': f'{type(e).__name__}: {e}'}


async def query(sql: str, params: tuple | list = ()) -> list:
	'''
	Run a read query against the IMDb database.

	:param sql: SQL statement
	:param params: Bound parameters
	'''

	db = await imdb_db()

	try:
		return await db.execute_fetchall(sql, params)
	finally:
		await db.close()


def read_status() -> dict:
	'''Return the importer status, or an empty dict if it has never run.'''

	try:
		return json.loads(importer.STATUS_PATH.read_text())
	except (FileNotFoundError, json.JSONDecodeError):
		return {}


async def recommend_titles(seeds: dict, limit: int = 60) -> list:
	'''
	Blend TMDB recommendations with local shared-people signals to recommend titles.

	:param seeds: Mapping of tconst to seed weight
	:param limit: Number of results
	'''

	top      = sorted(seeds.items(), key=lambda s: -s[1])[:60]
	details  = await asyncio.gather(*(tmdb_details(fmt_id('tt', tconst)) for tconst, _ in top))
	scores   = {}
	reasons  = {}
	resolved = {}

	def add(tconst: int, points: float, seed: int):
		scores[tconst] = scores.get(tconst, 0) + points
		reasons.setdefault(tconst, {}).setdefault(seed, 0)
		reasons[tconst][seed] += points

	for (seed, weight), data in zip(top, details):
		for rank, rec in enumerate((data or {}).get('recs', [])[:20]):
			key = (rec['title'], rec['year'])
			if key not in resolved:
				resolved[key] = await match_title(rec['title'], int(rec['year']) if rec['year'].isdigit() else None, REC_TYPES)
			if resolved[key]:
				add(resolved[key], weight * (1 - rank / 25), seed)

	seed_ids = [tconst for tconst, _ in top]
	people   = await query(f'''
		SELECT tconst, nconst, 1.5 AS w FROM crew WHERE role = 'director' AND tconst IN ({",".join("?" * len(seed_ids))})
		UNION ALL
		SELECT tconst, nconst, 1.0 FROM principals WHERE ordering <= 4 AND category IN ('actor', 'actress') AND tconst IN ({",".join("?" * len(seed_ids))})
	''', seed_ids * 2) if seed_ids else []
	weights  = {}
	origin   = {}

	for row in people:
		weights[row['nconst']] = weights.get(row['nconst'], 0) + row['w'] * seeds[row['tconst']]
		origin.setdefault(row['nconst'], row['tconst'])

	if weights:
		shared = await query(f'''
			SELECT c.tconst, c.nconst FROM crew c JOIN titles t ON t.tconst = c.tconst WHERE c.role = 'director' AND c.nconst IN ({",".join("?" * len(weights))}) AND t.type IN ({",".join("?" * len(REC_TYPES))}) AND t.votes >= 2000
			UNION ALL
			SELECT p.tconst, p.nconst FROM principals p JOIN titles t ON t.tconst = p.tconst WHERE p.ordering <= 4 AND p.nconst IN ({",".join("?" * len(weights))}) AND t.type IN ({",".join("?" * len(REC_TYPES))}) AND t.votes >= 2000
		''', [*weights, *REC_TYPES] * 2)
		for row in shared:
			add(row['tconst'], weights[row['nconst']] * 0.35, origin[row['nconst']])

	async with user_db() as db:
		watched = {r['tconst'] for r in await db.execute_fetchall("SELECT tconst FROM marks WHERE user_id = ? AND mark = 'watched'", (g.user['id'],))}

	candidates = [t for t in scores if t not in seeds and t not in watched]
	titles     = await titles_by_ids(candidates)
	seed_rows  = await titles_by_ids(seed_ids)
	ranked     = []

	for tconst, row in titles.items():
		if row['type'] in REC_TYPES and (row['votes'] or 0) >= 1000:
			because = [seed_rows[s]['primary_title'] for s, _ in sorted(reasons[tconst].items(), key=lambda r: -r[1])[:2] if s in seed_rows]
			ranked.append((scores[tconst] * (0.5 + (row['rating'] or 5) / 20), row, because))

	ranked.sort(key=lambda r: -r[0])

	return [{'t': row, 'because': because} for _, row, because in ranked[:limit]]


def require(admin: bool = False):
	'''
	Route decorator: send guests to the login page, and refuse non-admins on admin routes.

	:param admin: Only the admin account may use the route
	'''

	def decorator(func):
		@functools.wraps(func)
		async def wrapper(*args, **kwargs):
			if not g.user:
				return redirect('/login?' + urlencode({'next': request.full_path.rstrip('?')}))
			if admin and not g.user['admin']:
				abort(403)
			return await func(*args, **kwargs)
		return wrapper

	return decorator


async def scheduler():
	'''Hourly background loop: daily Letterboxd sync for every account, weekly IMDb rebuild, and weekly pre-cache.'''

	while True:
		try:
			async with user_db() as db:
				synced = [row['user_id'] for row in await db.execute_fetchall("SELECT s.user_id FROM user_settings s JOIN users u ON u.id = s.user_id WHERE s.key = 'letterboxd_user' AND s.value != '' AND u.approved = 1")]

			for user_id in synced:
				if time.time() - float(await user_setting('lb_last_sync', '0', user_id)) >= 86400 and not state['lb'].get(user_id, {}).get('running'):
					await letterboxd_sync(user_id)

			built = importer.DB_PATH.stat().st_mtime if importer.DB_PATH.exists() else 0
			if time.time() - built >= WEEK and read_status().get('state') != 'running':
				await start_import()

			if importer.DB_PATH.exists() and read_status().get('state') != 'running' and await setting('tmdb_key') and time.time() - float(await setting('precache_last', '0')) >= WEEK and not state['precache'].get('running'):
				spawn(precache())

			if importer.DB_PATH.exists() and await subtitle_accounts() and time.time() // 86400 > float(await setting('subs_last', '0')) // 86400 and not state['subs'].get('running'):
				spawn(subtitle_prefetch())
		except Exception as e:
			print(f'scheduler error: {type(e).__name__}: {e}', file=sys.stderr)

		await asyncio.sleep(min(3600, 86400 - time.time() % 86400 + 60))


async def search_titles(fts: str, limit: int, episodes: bool = False, types: tuple = ()) -> list:
	'''
	Search titles by FTS, trying the small popular index first so common words stay fast.

	:param fts: FTS5 query
	:param limit: Maximum results
	:param episodes: Search episodes instead of titles
	:param types: Only these title types (all when empty)
	'''

	if episodes:
		sql = 'SELECT t.*, e.season, e.episode, p.primary_title AS parent_title, p.tconst AS parent FROM {0} f JOIN titles t ON t.tconst = f.rowid JOIN episodes e ON e.tconst = t.tconst LEFT JOIN titles p ON p.tconst = e.parent WHERE {0} MATCH ? ORDER BY t.votes DESC LIMIT ?'
		tables = ('episodes_pop_fts', 'episodes_fts')
	else:
		sql    = 'SELECT t.* FROM {0} f JOIN titles t ON t.tconst = f.rowid WHERE {0} MATCH ?' + (f' AND t.type IN ({",".join("?" * len(types))})' if types else '') + ' ORDER BY t.votes DESC LIMIT ?'
		tables = ('titles_pop_fts', 'titles_fts')

	rows = await query(sql.format(tables[0]), (fts, *types, limit))

	return rows if len(rows) >= limit else await query(sql.format(tables[1]), (fts, *types, limit))


async def setting(key: str, default: str = '') -> str:
	'''
	Read a value from the settings table.

	:param key: Setting name
	:param default: Value when unset
	'''

	async with user_db() as db:
		rows = await db.execute_fetchall('SELECT value FROM settings WHERE key = ?', (key,))

	return rows[0]['value'] if rows else default


def spawn(coro):
	'''
	Run a coroutine in the background, keeping a reference so it is not garbage collected mid-run.

	:param coro: Coroutine to run
	'''

	task = asyncio.create_task(coro)
	tasks.add(task)
	task.add_done_callback(tasks.discard)


async def start_import():
	'''Start the IMDb importer in a subprocess if enough disk space is free.'''

	free = shutil.disk_usage(BASE_DIR).free
	need = (importer.DB_PATH.stat().st_size if importer.DB_PATH.exists() else 0) + 5_000_000_000

	if free < need:
		importer.STATUS_PATH.parent.mkdir(exist_ok=True)
		importer.STATUS_PATH.write_text(json.dumps({'state': 'error', 'step': 'Not started', 'rows': 0, 'progress': '', 'started': time.time(), 'finished': time.time(), 'error': f'not enough disk space: {free / 1e9:.1f} GB free, {need / 1e9:.1f} GB needed'}))
		return

	with open(importer.DATA_DIR / 'importer.log', 'w') as log:
		state['update'] = await asyncio.create_subprocess_exec(sys.executable, str(BASE_DIR / 'importer.py'), stdout=log, stderr=asyncio.subprocess.STDOUT)


async def stream_links(tconst: int, d: dict | None) -> list:
	'''
	Build third-party streaming links: the site's own page from the TMDB/IMDb id when it has one, otherwise a search for the title.

	:param tconst: Numeric title id
	:param d: TMDB details from tmdb_details()
	'''

	rows = await query('SELECT t.primary_title, t.type, p.primary_title AS show FROM titles t LEFT JOIN episodes e ON e.tconst = t.tconst LEFT JOIN titles p ON p.tconst = e.parent WHERE t.tconst = ?', (tconst,))

	if not rows:
		return []

	tv    = rows[0]['type'] in ('tvSeries', 'tvMiniSeries', 'tvEpisode')
	name  = quote(rows[0]['show'] or rows[0]['primary_title'])
	tmdb  = (d or {}).get('tmdb_id')
	links = []

	if (d or {}).get('kind') == 'episode':
		tmdb = int(m.group(1)) if (m := re.search(r'/tv/(\d+)', d['url'])) else None

	for site, base, movie, show, search in STREAM_SITES:
		path = show if tv else movie
		if path and ('{tmdb}' not in path or tmdb):
			links.append({'site': site, 'url': base + path.format(tmdb=tmdb, imdb=fmt_id('tt', tconst), q=name), 'direct': '{q}' not in path})
		elif search:
			links.append({'site': site, 'url': base + search.format(q=name), 'direct': False})

	return links


async def subtitle_accounts() -> list:
	'''Return the shared pool of subtitle keys: one entry per SubDL key and per OpenSubtitles key saved by any approved account.'''

	async with user_db() as db:
		rows = await db.execute_fetchall('SELECT k.* FROM subtitle_keys k JOIN users u ON u.id = k.user_id WHERE u.approved = 1')

	pool = []

	for row in rows:
		if row['subdl_key']:
			pool.append({'id': f'subdl:{row["user_id"]}', 'provider': 'subdl', 'key': row['subdl_key']})
		if row['os_key']:
			pool.append({'id': f'os:{row["user_id"]}', 'provider': 'os', 'key': row['os_key'], 'user': row['os_user'], 'pass': row['os_pass']})

	return pool


async def subtitle_download(tconst: int, provider: str, sub_id: str, release: str, accounts: list | None = None) -> Path:
	'''
	Download an English subtitle to data/subs/tt.../<release>.srt unless it is already there. Raises RuntimeError on failure.

	:param tconst: Numeric title id
	:param provider: 'subdl' or 'os'
	:param sub_id: SubDL download path or OpenSubtitles file id
	:param release: Release name, used as the file name
	:param accounts: Pooled keys to try for OpenSubtitles (default: the whole pool, in random order)
	'''

	path = SUBS_DIR / fmt_id('tt', tconst) / subtitle_name(release)

	if path.exists():
		return path

	if provider == 'subdl':
		try:
			async with state['session'].get(f'https://dl.subdl.com{sub_id}', headers={'User-Agent': USER_AGENT}) as response:
				if response.status != 200:
					raise RuntimeError(f'SubDL download returned HTTP {response.status}')
				body = await response.read()
		except (aiohttp.ClientError, asyncio.TimeoutError) as e:
			raise RuntimeError(f'SubDL download failed: {type(e).__name__}') from e

		if not zipfile.is_zipfile(io.BytesIO(body)):
			raise RuntimeError('SubDL archive is not a zip (probably RAR), try another subtitle')

		with zipfile.ZipFile(io.BytesIO(body)) as archive:
			names = [n for n in archive.namelist() if n.lower().endswith('.srt')]
			if not names:
				raise RuntimeError('SubDL archive has no .srt file')
			ep = await subtitle_target(tconst)
			if ep and len(names) > 1:
				names = [n for n in names if re.search(rf'(?i)s0*{ep["season"]}\s*e0*{ep["episode"]}(?!\d)|\b{ep["season"]}x0*{ep["episode"]}(?!\d)', n)] or names
			body = archive.read(names[0])
	elif provider == 'os':
		candidates = [a for a in (accounts if accounts is not None else await subtitle_accounts()) if a['provider'] == 'os']
		random.shuffle(candidates)
		if not candidates:
			raise RuntimeError('no OpenSubtitles key')
		for account in candidates:
			try:
				link = await opensubtitles_request(account, 'POST', 'download', auth=True, json={'file_id': int(sub_id)})
				break
			except RuntimeError as e:
				error = e
		else:
			raise error
		for attempt in range(3):
			try:
				async with state['session'].get(link['link']) as response:
					if response.status != 200:
						raise RuntimeError(f'OpenSubtitles download returned HTTP {response.status}')
					body = await response.read()
				break
			except (aiohttp.ClientError, asyncio.TimeoutError) as e:
				if attempt == 2:
					raise RuntimeError(f'OpenSubtitles download failed: {type(e).__name__}') from e
	else:
		raise RuntimeError(f'unknown provider {provider}')

	try:
		body.decode('utf-8')
	except UnicodeDecodeError:
		try:
			body = body.decode('cp1252').encode('utf-8')
		except UnicodeDecodeError:
			pass

	path.parent.mkdir(parents=True, exist_ok=True)
	path.with_suffix('.part').write_bytes(body)
	path.with_suffix('.part').replace(path)

	return path


def subtitle_files(tconst: int) -> list:
	'''
	Return the names of the downloaded subtitle files for a title.

	:param tconst: Numeric title id
	'''

	folder = SUBS_DIR / fmt_id('tt', tconst)

	return sorted(f.name for f in folder.glob('*.srt')) if folder.exists() else []


def subtitle_name(release: str) -> str:
	'''
	Turn a release name into a safe subtitle file name.

	:param release: Release name
	'''

	return (re.sub(r'[^\w.\- ]+', '_', release).strip(' ._')[:150] or 'subtitle') + '.srt'


async def subtitle_quota() -> dict:
	'''Return the daily download quota (left, limit, reset as a unix time) of every pooled subtitle key as reported by its provider's API, plus per-provider totals.'''

	async def check(account: dict) -> dict:
		account |= {'left': 0, 'limit': 0, 'reset': None}
		try:
			if account['provider'] == 'subdl':
				async with state['session'].get('https://api.subdl.com/api/v2/me', headers={'Authorization': f'Bearer {account["key"]}'}) as response:
					data = (await response.json(content_type=None))['usage']['downloads']
				account |= {'left': int(data['remaining']), 'limit': int(data['limit']), 'reset': datetime.fromisoformat(data['reset_at']).timestamp()}
			elif account['user']:
				data = (await opensubtitles_request(account, 'GET', 'infos/user', auth=True))['data']
				account |= {'left': int(data['remaining_downloads']), 'limit': int(data['allowed_downloads']), 'reset': datetime.fromisoformat(data['reset_time_utc']).timestamp() if data.get('reset_time_utc') else None}
		except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError, KeyError, TypeError):
			pass
		return account

	accounts = await asyncio.gather(*(check(a) for a in await subtitle_accounts()))
	quota    = {'accounts': accounts}

	for provider in ('subdl', 'os'):
		mine = [a for a in accounts if a['provider'] == provider and (provider == 'subdl' or a['user'])]
		quota[provider] = {'enabled': bool(mine), 'count': len(mine), 'left': sum(a['left'] for a in mine), 'limit': sum(a['limit'] for a in mine), 'reset': min((a['reset'] for a in mine if a['reset']), default=None)}

	return quota


async def subtitle_prefetch():
	'''Download the best English subtitle for library titles that have none, until the providers' daily download quotas run out.'''

	state['subs'] = {'running': True, 'done': 0, 'error': None}

	try:
		async with user_db() as db:
			library  = [r[0] for r in await db.execute_fetchall("SELECT tconst FROM marks WHERE mark = 'watchlist' UNION SELECT tconst FROM list_items UNION SELECT tconst FROM marks WHERE mark = 'watched'")]
			searched = {r['tconst']: (json.loads(r['data']), r['fetched']) for r in await db.execute_fetchall('SELECT * FROM subtitles')}

		titles                 = await titles_by_ids(library)
		state['subs']['quota'] = quota = await subtitle_quota()
		had_quota              = any(a['left'] for a in quota['accounts'])

		for tconst in library:
			pool = [a for a in quota['accounts'] if a['left'] > 0]
			if not (allowed := tuple(dict.fromkeys(a['provider'] for a in pool))):
				break
			if tconst not in titles or titles[tconst]['type'] in ('tvSeries', 'tvMiniSeries') or subtitle_files(tconst):
				continue
			results, fetched = searched.get(tconst, (None, 0))
			fresh            = time.time() - fetched < WEEK
			if fresh and results == []:
				continue
			usable = [r for r in results or [] if r['provider'] in allowed] if fresh else []
			if not usable:
				usable = [r for r in await subtitle_search(tconst, allowed, pool) if r['provider'] in allowed]
			if usable:
				best    = sorted(usable, key=lambda s: s['hi'] or bool(re.search(r'(?i)\b(sdh|hi)\b', s['release'])))[0]
				account = next(a for a in pool if a['provider'] == best['provider'])
				try:
					await subtitle_download(tconst, best['provider'], best['id'], best['release'], [account])
					state['subs']['done'] += 1
				except RuntimeError as e:
					state['subs']['error'] = str(e)
				account['left']                -= 1
				quota[best['provider']]['left'] -= 1

		if had_quota:
			async with user_db() as db:
				await db.executemany('INSERT OR REPLACE INTO settings VALUES (?, ?)', [('subs_last', str(time.time())), ('subs_done', str(state['subs']['done']))])
				await db.commit()

		state['subs'] = {'running': False, 'done': state['subs']['done'], 'error': state['subs']['error']}
	except Exception as e:
		state['subs'] = {'running': False, 'done': state['subs']['done'], 'error': f'{type(e).__name__}: {e}'}


async def subtitle_search(tconst: int, providers: tuple = ('subdl', 'os'), accounts: list | None = None) -> list:
	'''
	Search SubDL, then OpenSubtitles if SubDL found nothing, for English subtitles, and cache the results. Each provider uses a random key from the pool. Raises RuntimeError when every provider failed.

	:param tconst: Numeric title id
	:param providers: Providers to search
	:param accounts: Pooled keys to pick from (default: the whole pool)
	'''

	ep      = await subtitle_target(tconst)
	pool    = accounts if accounts is not None else await subtitle_accounts()
	subdl   = [a for a in pool if a['provider'] == 'subdl']
	os_keys = [a for a in pool if a['provider'] == 'os']
	results = []
	errors  = []

	if 'subdl' in providers and subdl:
		params = {'api_key': random.choice(subdl)['key'], 'languages': 'EN', 'subs_per_page': 30} | ({'imdb_id': fmt_id('tt', ep['parent']), 'type': 'tv', 'season_number': ep['season'], 'episode_number': ep['episode']} if ep else {'imdb_id': fmt_id('tt', tconst), 'type': 'movie'})
		try:
			async with state['session'].get('https://api.subdl.com/api/v1/subtitles', params=params) as response:
				data = await response.json(content_type=None)
			if response.status != 200:
				raise RuntimeError(data.get('message') or data.get('error') or f'HTTP {response.status}')
			results = [{'provider': 'subdl', 'id': s['url'], 'release': s.get('release_name') or s.get('name') or 'subtitle', 'hi': bool(s.get('hi')), 'downloads': None} for s in data.get('subtitles') or [] if s.get('url')]
		except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, RuntimeError) as e:
			errors.append(f'SubDL: {e}')

	if not results and 'os' in providers and os_keys:
		params = {'languages': 'en'} | ({'parent_imdb_id': ep['parent'], 'season_number': ep['season'], 'episode_number': ep['episode']} if ep else {'imdb_id': tconst})
		try:
			data    = await opensubtitles_request(random.choice(os_keys), 'GET', 'subtitles', params=sorted(params.items()))
			results = [{'provider': 'os', 'id': str(a['files'][0]['file_id']), 'release': a.get('release') or a['files'][0].get('file_name') or 'subtitle', 'hi': bool(a.get('hearing_impaired')), 'downloads': a.get('download_count')} for a in (d['attributes'] for d in data.get('data', [])) if a.get('files')]
			results.sort(key=lambda s: -(s['downloads'] or 0))
		except RuntimeError as e:
			errors.append(f'OpenSubtitles: {e}')

	if not results and errors:
		raise RuntimeError('; '.join(errors))

	async with user_db() as db:
		await db.execute('INSERT OR REPLACE INTO subtitles VALUES (?, ?, ?)', (tconst, json.dumps(results), time.time()))
		await db.commit()

	return results


async def subtitle_target(tconst: int):
	'''
	Return the parent show, season and episode row for an episode, or None for anything else.

	:param tconst: Numeric title id
	'''

	rows = await query('SELECT parent, season, episode FROM episodes WHERE tconst = ?', (tconst,))

	if rows and rows[0]['parent'] and rows[0]['season'] is not None and rows[0]['episode'] is not None:
		return rows[0]

	return None


async def titles_by_ids(ids: list) -> dict:
	'''
	Fetch title rows keyed by tconst.

	:param ids: List of integer tconsts
	'''

	if not ids:
		return {}

	rows = await query(f'SELECT * FROM titles WHERE tconst IN ({",".join("?" * len(ids))})', ids)

	return {row['tconst']: row for row in rows}


async def tmdb_cached(cache_id: str, path: str, ttl: int, params: dict | None = None) -> dict | None:
	'''
	Fetch an arbitrary TMDB endpoint through the tmdb cache table, falling back to stale data when offline.

	:param cache_id: Cache key
	:param path: API path after /3/
	:param ttl: Seconds before refreshing
	:param params: Query parameters
	'''

	async with user_db() as db:
		rows = await db.execute_fetchall('SELECT data, fetched FROM tmdb WHERE id = ?', (cache_id,))

	stale = json.loads(rows[0]['data']) if rows and rows[0]['data'] else None

	if rows and time.time() - rows[0]['fetched'] < ttl:
		return stale

	if not (key := await setting('tmdb_key')) or (data := await tmdb_request(path, key, params)) is None:
		return stale

	async with user_db() as db:
		await db.execute('INSERT OR REPLACE INTO tmdb VALUES (?, ?, ?)', (cache_id, json.dumps(data), time.time()))
		await db.commit()

	return data


async def tmdb_details(imdb_id: str, cached_only: bool = False) -> dict | None:
	'''
	Return enriched TMDB details for a title or person, cached in the user database and refreshed after a TTL.

	:param imdb_id: IMDb id (tt... or nm...)
	:param cached_only: Never hit the network
	'''

	async with user_db() as db:
		rows = await db.execute_fetchall('SELECT data, fetched FROM tmdb WHERE id = ?', (imdb_id,))

	data = json.loads(rows[0]['data']) if rows and rows[0]['data'] else None

	if rows and (cached_only or time.time() - rows[0]['fetched'] < (TMDB_TTL.get(data['kind'], 30 * 86400) if data else WEEK)):
		return data

	if cached_only or not (key := await setting('tmdb_key')):
		return data

	fresh = await tmdb_fetch(imdb_id, key)

	if fresh is False:
		return data

	async with user_db() as db:
		await db.execute('INSERT OR REPLACE INTO tmdb VALUES (?, ?, ?)', (imdb_id, json.dumps(fresh) if fresh else None, time.time()))
		if imdb_id.startswith('tt'):
			await db.execute('DELETE FROM title_providers WHERE tconst = ?', (int(imdb_id[2:]),))
			await db.executemany('INSERT OR IGNORE INTO title_providers VALUES (?, ?)', [(int(imdb_id[2:]), p['id']) for p in (fresh or {}).get('providers', [])])
		await db.commit()

	return fresh


async def tmdb_fetch(imdb_id: str, key: str) -> dict | None | bool:
	'''
	Fetch and normalize TMDB details for an IMDb id. Returns None when TMDB has no match and False on network failure.

	:param imdb_id: IMDb id (tt... or nm...)
	:param key: TMDB API key
	'''

	found = await tmdb_request(f'find/{imdb_id}', key, {'external_source': 'imdb_id'})

	if found is None:
		return False

	if item := next(iter(found.get('movie_results', [])), None):
		if (d := await tmdb_request(f'movie/{item["id"]}', key, {'append_to_response': 'videos,release_dates,keywords,credits,watch/providers,recommendations'})) is None:
			return False
		us      = next((r['release_dates'] for r in d.get('release_dates', {}).get('results', []) if r['iso_3166_1'] == 'US'), [])
		credits = d.get('credits', {})
		data    = {
			'kind'          : 'movie',
			'url'           : f'https://www.themoviedb.org/movie/{item["id"]}',
			'release_date'  : d.get('release_date'),
			'certification' : next((r['certification'] for r in us if r['certification']), None),
			'budget'        : d.get('budget'),
			'revenue'       : d.get('revenue'),
			'collection'    : (d.get('belongs_to_collection') or {}).get('name'),
			'keywords'      : [k['name'] for k in d.get('keywords', {}).get('keywords', [])],
			'cast'          : [{'id': c['id'], 'name': c['name'], 'character': c.get('character'), 'profile': c.get('profile_path')} for c in credits.get('cast', [])[:300]],
			'crew'          : [{'id': c['id'], 'name': c['name'], 'job': c.get('job'), 'department': c.get('department'), 'profile': c.get('profile_path')} for c in credits.get('crew', [])[:300]]
		}
	elif item := next(iter(found.get('tv_results', [])), None):
		if (d := await tmdb_request(f'tv/{item["id"]}', key, {'append_to_response': 'videos,content_ratings,keywords,aggregate_credits,watch/providers,recommendations'})) is None:
			return False
		next_ep = d.get('next_episode_to_air') or {}
		credits = d.get('aggregate_credits', {})
		data    = {
			'kind'          : 'tv',
			'url'           : f'https://www.themoviedb.org/tv/{item["id"]}',
			'first_air'     : d.get('first_air_date'),
			'last_air'      : d.get('last_air_date'),
			'next_episode'  : f'S{next_ep["season_number"]}E{next_ep["episode_number"]} · {next_ep.get("name", "")} · {next_ep.get("air_date", "")}' if next_ep else None,
			'certification' : next((r['rating'] for r in d.get('content_ratings', {}).get('results', []) if r['iso_3166_1'] == 'US'), None),
			'networks'      : [n['name'] for n in d.get('networks', [])],
			'created_by'    : [c['name'] for c in d.get('created_by', [])],
			'seasons'       : d.get('number_of_seasons'),
			'episodes'      : d.get('number_of_episodes'),
			'keywords'      : [k['name'] for k in d.get('keywords', {}).get('results', [])],
			'cast'          : [{'id': c['id'], 'name': c['name'], 'character': ' / '.join(r['character'] for r in c.get('roles', []) if r.get('character')), 'episodes': c.get('total_episode_count'), 'profile': c.get('profile_path')} for c in credits.get('cast', [])[:300]],
			'crew'          : [{'id': c['id'], 'name': c['name'], 'job': ', '.join(j['job'] for j in c.get('jobs', [])), 'department': c.get('department'), 'episodes': c.get('total_episode_count'), 'profile': c.get('profile_path')} for c in credits.get('crew', [])[:300]]
		}
	elif item := next(iter(found.get('tv_episode_results', [])), None):
		d    = item
		data = {'kind': 'episode', 'url': f'https://www.themoviedb.org/tv/{item["show_id"]}/season/{item["season_number"]}/episode/{item["episode_number"]}', 'air_date': item.get('air_date'), 'poster_path': item.get('still_path')}
	elif item := next(iter(found.get('person_results', [])), None):
		if (d := await tmdb_request(f'person/{item["id"]}', key)) is None:
			return False
		data = {
			'kind'          : 'person',
			'url'           : f'https://www.themoviedb.org/person/{item["id"]}',
			'biography'     : d.get('biography'),
			'birthday'      : d.get('birthday'),
			'deathday'      : d.get('deathday'),
			'place_of_birth': d.get('place_of_birth'),
			'also_known_as' : d.get('also_known_as', []),
			'department'    : d.get('known_for_department'),
			'profile_path'  : d.get('profile_path')
		}
	else:
		return None

	data['tmdb_id'] = item['id']

	if data['kind'] != 'person':
		videos    = [v for v in d.get('videos', {}).get('results', []) if v['site'] == 'YouTube' and v['type'] in ('Trailer', 'Teaser')]
		watch     = d.get('watch/providers', {}).get('results', {}).get('US', {})
		providers = {}
		videos.sort(key=lambda v: (v['type'] != 'Trailer', not v.get('official')))

		for kind in ('flatrate', 'free', 'ads'):
			for p in watch.get(kind, []):
				providers.setdefault(p['provider_id'], {'id': p['provider_id'], 'name': p['provider_name'], 'logo': p.get('logo_path'), 'type': kind})

		data |= {
			'overview'      : d.get('overview'),
			'tagline'       : d.get('tagline'),
			'status'        : d.get('status'),
			'homepage'      : d.get('homepage'),
			'backdrop_path' : d.get('backdrop_path'),
			'poster_path'   : data.get('poster_path') or d.get('poster_path'),
			'trailer'       : videos[0]['key'] if videos else None,
			'countries'     : [c['name'] for c in d.get('production_countries', [])],
			'languages'     : [l['english_name'] for l in d.get('spoken_languages', [])],
			'companies'     : [c['name'] for c in d.get('production_companies', [])],
			'tmdb_rating'   : d.get('vote_average'),
			'tmdb_votes'    : d.get('vote_count'),
			'providers'     : list(providers.values()),
			'providers_link': watch.get('link'),
			'recs'          : [{'id': r['id'], 'kind': r.get('media_type', data['kind']), 'title': r.get('title') or r.get('name') or '', 'year': (r.get('release_date') or r.get('first_air_date') or '')[:4]} for r in d.get('recommendations', {}).get('results', [])]
		}

	return data


async def tmdb_request(path: str, key: str, params: dict | None = None) -> dict | None:
	'''
	Make a rate-limited TMDB API request, returning the decoded JSON or None on failure.

	:param path: API path after /3/
	:param key: TMDB v3 API key or v4 read access token
	:param params: Query parameters
	'''

	params  = dict(params or {})
	headers = {}

	if len(key) > 40:
		headers['Authorization'] = f'Bearer {key}'
	else:
		params['api_key'] = key

	for _ in range(3):
		async with state['tmdb_lock']:
			if (wait := state['tmdb_last'] + 1 / TMDB_RATE - time.monotonic()) > 0:
				await asyncio.sleep(wait)
			state['tmdb_last'] = time.monotonic()

		try:
			async with state['session'].get(f'https://api.themoviedb.org/3/{path}', params=params, headers=headers) as response:
				if response.status == 429:
					await asyncio.sleep(float(response.headers.get('Retry-After', 2)))
					continue
				return await response.json() if response.status == 200 else None
		except (aiohttp.ClientError, asyncio.TimeoutError):
			return None

	return None


async def torrent_search(tconst: int) -> tuple:
	'''
	Search bitmagnet's Torznab API by IMDb id (episodes search their show). Returns the 10 torrents with the most seeders, the total match count, and a web UI search URL (None for non-admins on the shared server). Raises RuntimeError on failure.

	:param tconst: Numeric title id
	'''

	rows = await query('SELECT t.type, t.primary_title, e.parent, p.primary_title AS show FROM titles t LEFT JOIN episodes e ON e.tconst = t.tconst LEFT JOIN titles p ON p.tconst = e.parent WHERE t.tconst = ?', (tconst,))

	if not rows:
		return [], 0, None

	own   = await user_setting('bm_url') if g.user else ''
	base  = (own or await setting('bm_url')).rstrip('/')
	url   = base + '/torznab/api'
	auth  = aiohttp.BasicAuth(await setting('bm_user'), await setting('bm_pass')) if not own and await setting('bm_user') else None
	more  = own or (g.user and g.user['admin'])
	kind  = 'tvsearch' if rows[0]['parent'] or rows[0]['type'] in ('tvSeries', 'tvMiniSeries') else 'movie'
	items = []

	for offset in range(0, 1000, 100):
		try:
			async with state['session'].get(url, params={'t': kind, 'imdbid': fmt_id('tt', rows[0]['parent'] or tconst), 'offset': offset}, auth=auth, headers={'User-Agent': USER_AGENT}) as response:
				if response.status != 200:
					raise RuntimeError(f'bitmagnet returned HTTP {response.status}')
				page = ElementTree.fromstring(await response.read()).findall('./channel/item')
		except (aiohttp.ClientError, asyncio.TimeoutError, ElementTree.ParseError) as e:
			raise RuntimeError(f'bitmagnet request failed: {type(e).__name__}') from e
		for item in page:
			attrs = {a.get('name'): a.get('value') for a in item.findall('{http://torznab.com/schemas/2015/feed}attr')}
			items.append({'title': item.findtext('title'), 'size': int(attrs.get('size') or 0), 'seeders': int(attrs.get('seeders') or 0), 'leechers': int(attrs.get('leechers') or 0), 'resolution': attrs.get('resolution'), 'magnet': attrs.get('magneturl')})
		if len(page) < 100:
			break

	return sorted(items, key=lambda t: -t['seeders'])[:10], len(items), f'{base}/webui/torrents?{urlencode({"query": rows[0]["show"] or rows[0]["primary_title"]})}' if more else None


def valid_https_url(url: str) -> bool:
	'''
	Check that a URL is https:// on an RFC 1123 hostname with a dot and an alphabetic TLD (no IP addresses, no userinfo).

	:param url: URL to check
	'''

	try:
		parts = urlsplit(url)
		parts.port
	except ValueError:
		return False

	host = parts.hostname or ''

	return parts.scheme == 'https' and '@' not in parts.netloc and len(host) <= 253 and re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})', host) is not None


async def user_setting(key: str, default: str = '', user_id: int | None = None) -> str:
	'''
	Read one of an account's own settings.

	:param key: Setting name
	:param default: Value when unset
	:param user_id: Account id (default: the logged-in account)
	'''

	async with user_db() as db:
		rows = await db.execute_fetchall('SELECT value FROM user_settings WHERE user_id = ? AND key = ?', (user_id or g.user['id'], key))

	return rows[0]['value'] if rows else default


@asynccontextmanager
async def user_db():
	'''Open a connection to the user database (lists, settings, caches).'''

	async with aiosqlite.connect(USER_DB, timeout=30) as db:
		db.row_factory = aiosqlite.Row
		yield db


@app.before_serving
async def startup():
	'''Create the user database schema and admin account, the shared HTTP session, and the background scheduler.'''

	async with user_db() as db:
		if 'user_id' not in [row['name'] for row in await db.execute_fetchall('PRAGMA table_info(ratings)')]:
			for table in ('ratings', 'marks', 'follows', 'lb_unmatched'):
				if await db.execute_fetchall("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)):
					await db.execute(f'ALTER TABLE {table} RENAME TO {table}_old')
		await db.executescript(USER_SCHEMA)
		await db.execute("INSERT OR IGNORE INTO users (id, name, admin, approved, created) VALUES (1, 'admin', 1, 1, ?)", (time.time(),))
		await migrate_users(db)
		admin = (await db.execute_fetchall('SELECT password FROM users WHERE id = 1'))[0]['password']
		if (password := os.environ.get('ADMIN_PASSWORD')) and not await asyncio.to_thread(password_check, password, admin):
			await db.execute('UPDATE users SET password = ? WHERE id = 1', (await asyncio.to_thread(password_hash, password),))
			await db.execute('DELETE FROM sessions WHERE user_id = 1')
		await db.commit()

	if not os.environ.get('ADMIN_PASSWORD'):
		print('ADMIN_PASSWORD is not set in .env, the admin account keeps its previous password', file=sys.stderr)

	if (status := read_status()).get('state') == 'running':
		importer.STATUS_PATH.write_text(json.dumps(status | {'state': 'error', 'finished': time.time(), 'error': 'interrupted by an app restart'}))

	state['session']   = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15), headers={'User-Agent': USER_AGENT})
	state['tmdb_lock'] = asyncio.Lock()
	state['scheduler'] = asyncio.create_task(scheduler())
	state['images_at'] = time.time()
	spawn(image_usage())


@app.before_request
async def load_user():
	'''Look up the logged-in account from the session cookie.'''

	g.user = None

	if (token := request.cookies.get('session')) and not request.path.startswith('/static/'):
		async with user_db() as db:
			rows = await db.execute_fetchall('SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ? AND s.expires > ? AND u.approved = 1', (hashlib.sha256(token.encode()).hexdigest(), time.time()))
		g.user = rows[0] if rows else None


@app.after_serving
async def shutdown():
	'''Close the shared HTTP session.'''

	await state['session'].close()


@app.context_processor
def inject():
	'''Expose helpers to all templates.'''

	def page_url(page: int) -> str:
		args = request.args.to_dict(flat=False) | {'page': [page]}
		return f'{request.path}?{urlencode(args, doseq=True)}'

	def img(path: str | None, size: str = 'w185') -> str:
		return f'/img/{size}{path}' if path else ''

	return {'fmt_id': fmt_id, 'json': json, 'page_url': page_url, 'img': img, 'status': read_status(), 'no_photo': 'data:image/svg+xml,' + quote(NO_PHOTO), 'user': g.get('user')}


@app.context_processor
async def inject_mine():
	'''Expose the logged-in account's marks, ratings, follows, and streaming providers to all templates (all empty for guests).'''

	if not g.get('user'):
		return {'mine': {'watched': set(), 'watchlist': set(), 'tt': {}, 'nm': {}, 'follows': set(), 'providers': set()}}

	async with user_db() as db:
		marks   = await db.execute_fetchall('SELECT tconst, mark FROM marks WHERE user_id = ?', (g.user['id'],))
		ratings = await db.execute_fetchall('SELECT kind, id, rating FROM ratings WHERE user_id = ?', (g.user['id'],))
		follows = await db.execute_fetchall('SELECT nconst FROM follows WHERE user_id = ?', (g.user['id'],))

	return {'mine': {'watched': {m['tconst'] for m in marks if m['mark'] == 'watched'}, 'watchlist': {m['tconst'] for m in marks if m['mark'] == 'watchlist'}, 'tt': {r['id']: r['rating'] for r in ratings if r['kind'] == 'tt'}, 'nm': {r['id']: r['rating'] for r in ratings if r['kind'] == 'nm'}, 'follows': {f['nconst'] for f in follows}, 'providers': set(await my_providers())}}


@app.template_filter('datetime')
def datetime_filter(timestamp: int) -> str:
	'''
	Format a unix timestamp for display.

	:param timestamp: Unix timestamp
	'''

	return time.strftime('%Y-%m-%d %H:%M', time.localtime(timestamp))


@app.errorhandler(404)
async def not_found(_):
	'''Show the custom 404 page.'''

	return await render_template('404.html'), 404


@app.errorhandler(503)
async def not_built(_):
	'''Show the build status page when the database is missing.'''

	return await render_template('building.html'), 503


@app.route('/account', methods=['POST'])
@require()
async def account():
	'''Change the logged-in account's password, or delete the account. Both need the current password.'''

	form = await request.form

	if g.user['admin']:
		abort(403)

	if not await asyncio.to_thread(password_check, form.get('current', ''), g.user['password']):
		return redirect('/settings?account=wrong')

	if form.get('action') == 'delete':
		await delete_user(g.user['id'])
		response = redirect('/')
		response.delete_cookie('session')
		return response

	if not 6 <= len(password := form.get('password', '')) <= 100:
		return redirect('/settings?account=length')

	async with user_db() as db:
		await db.execute('UPDATE users SET password = ? WHERE id = ?', (await asyncio.to_thread(password_hash, password), g.user['id']))
		await db.execute('DELETE FROM sessions WHERE user_id = ? AND token != ?', (g.user['id'], hashlib.sha256(request.cookies['session'].encode()).hexdigest()))
		await db.commit()

	return redirect('/settings?account=changed')


@app.route('/admin', methods=['GET', 'POST'])
@require(admin=True)
async def admin():
	'''View the site settings, accounts and database status, and apply changes to them.'''

	if request.method == 'GET':
		async with user_db() as db:
			cached = await db.execute_fetchall('SELECT source, count(*) AS count FROM posters GROUP BY source')
			tmdb_n = (await db.execute_fetchall("SELECT count(*) AS n FROM tmdb WHERE data IS NOT NULL AND (id LIKE 'tt%' OR id LIKE 'nm%')"))[0]['n']
			users  = await db.execute_fetchall('''
				SELECT u.id, u.name, u.admin, u.approved, u.created,
					(SELECT count(*) FROM lists WHERE user_id = u.id) AS lists,
					(SELECT count(*) FROM ratings WHERE user_id = u.id) AS ratings,
					(SELECT count(*) FROM marks WHERE user_id = u.id) AS marks,
					EXISTS (SELECT 1 FROM subtitle_keys k WHERE k.user_id = u.id AND (k.subdl_key != '' OR k.os_key != '')) AS sub_keys,
					(SELECT max(expires) FROM sessions WHERE user_id = u.id) - ? AS last_login
				FROM users u ORDER BY u.approved, u.admin DESC, u.created DESC
			''', (SESSION_AGE,))

		meta = await query('SELECT * FROM meta') if importer.DB_PATH.exists() else []
		size = importer.DB_PATH.stat().st_size if importer.DB_PATH.exists() else 0

		if time.time() - state['images_at'] >= 600:
			state['images_at'] = time.time()
			spawn(image_usage())

		return await render_template('admin.html', users=users, registration=await setting('registration', 'open'), approval=await setting('approval', '1'), tmdb_key=await setting('tmdb_key'), cached=cached, tmdb_n=tmdb_n, images=state['images'], meta={m['key']: m['value'] for m in meta}, size=size, bm={key: await setting(key) for key in ('bm_url', 'bm_user', 'bm_pass')})

	form    = await request.form
	action  = form.get('action')
	user_id = form.get('user_id', 0, type=int)

	if action == 'delete' and user_id != 1:
		await delete_user(user_id)

	async with user_db() as db:
		if action == 'registration':
			await db.executemany('INSERT OR REPLACE INTO settings VALUES (?, ?)', [('registration', 'open' if form.get('registration') else 'closed'), ('approval', '1' if form.get('approval') else '0')])
		elif action == 'approve':
			await db.execute('UPDATE users SET approved = 1 WHERE id = ?', (user_id,))
		elif action == 'password' and user_id != 1 and 6 <= len(password := form.get('password', '')) <= 100:
			await db.execute('UPDATE users SET password = ? WHERE id = ?', (await asyncio.to_thread(password_hash, password), user_id))
			await db.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
		for key in ('tmdb_key', 'bm_url', 'bm_user', 'bm_pass'):
			if key in form:
				await db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, form[key].strip()))
		if form.get('clear_posters'):
			await db.execute('DELETE FROM posters')
			await db.execute("DELETE FROM tmdb WHERE id LIKE 'tt%' OR id LIKE 'nm%'")
			await db.execute('DELETE FROM title_providers')
			shutil.rmtree(IMAGE_DIR, ignore_errors=True)
			state['images_at'] = 0.0
		await db.commit()

	return redirect('/admin#accounts' if action else '/admin')


@app.route('/captcha/<token>.svg')
async def captcha(token: str):
	'''
	Draw a register captcha.

	:param token: Captcha id from captcha_new()
	'''

	if token not in state['captchas']:
		abort(404)

	return Response(captcha_svg(state['captchas'][token][0]), mimetype='image/svg+xml', headers={'Cache-Control': 'no-store'})


@app.route('/favicon.ico')
async def favicon():
	'''Serve the favicon for clients that request /favicon.ico directly.'''

	return await app.send_static_file('icons/favicon-32.png')


@app.route('/go/tmdb/<kind>/<int:tmdb_id>')
async def go_tmdb(kind: str, tmdb_id: int):
	'''
	Resolve a TMDB id to the local IMDb page, falling back to a search or the TMDB page.

	:param kind: 'movie', 'tv', or 'person'
	:param tmdb_id: TMDB id
	'''

	if kind not in ('movie', 'tv', 'person'):
		abort(404)

	async with user_db() as db:
		rows = await db.execute_fetchall('SELECT imdb_id FROM tmdb_ids WHERE kind = ? AND tmdb_id = ?', (kind, tmdb_id))

	imdb_id = rows[0]['imdb_id'] if rows else None

	if not rows and (key := await setting('tmdb_key')) and (ids := await tmdb_request(f'{kind}/{tmdb_id}/external_ids', key)) is not None:
		imdb_id = ids.get('imdb_id')
		async with user_db() as db:
			await db.execute('INSERT OR REPLACE INTO tmdb_ids VALUES (?, ?, ?)', (kind, tmdb_id, imdb_id))
			await db.commit()

	if imdb_id:
		return redirect(f'/{"name" if kind == "person" else "title"}/{imdb_id}')

	if name := request.args.get('name'):
		return redirect(f'/search?{urlencode({"q": name})}')

	return redirect(f'https://www.themoviedb.org/{kind}/{tmdb_id}')


@app.route('/img/<size>/<filename>')
async def tmdb_image(size: str, filename: str):
	'''
	Serve a TMDB image from the local cache, downloading it on first request.

	:param size: TMDB image size
	:param filename: TMDB image file name
	'''

	if size not in IMG_SIZES or not re.fullmatch(r'[A-Za-z0-9_-]+\.(jpg|png|svg)', filename):
		abort(404)

	path = IMAGE_DIR / 'tmdb' / size / filename

	if path.exists() or await download(f'https://image.tmdb.org/t/p/{size}/{filename}', path):
		return await send_file(path, cache_timeout=30 * 86400)

	return Response(PLACEHOLDER, mimetype='image/svg+xml', headers={'Cache-Control': 'no-store'})


@app.route('/')
async def index():
	'''Home page with highlights.'''

	year    = time.localtime().tm_year
	popular = await query("SELECT * FROM titles WHERE type = 'movie' ORDER BY votes DESC LIMIT 12")
	recent  = await query("SELECT * FROM titles WHERE type = 'movie' AND start_year >= ? ORDER BY votes DESC LIMIT 12", (year - 1,))
	series  = await query("SELECT * FROM titles WHERE type IN ('tvSeries', 'tvMiniSeries') ORDER BY votes DESC LIMIT 12")

	return await render_template('index.html', popular=popular, recent=recent, series=series)


@app.route('/letterboxd/fix', methods=['GET', 'POST'])
@require()
async def lb_fix():
	'''List Letterboxd films that couldn't be matched and let the user pick the right IMDb title (POST applies it).'''

	if request.method == 'POST':
		form = await request.form

		async with user_db() as db:
			rows = await db.execute_fetchall('SELECT * FROM lb_unmatched WHERE user_id = ? AND key = ?', (g.user['id'], form['key']))
			if rows and (tconst := form.get('tconst', type=int)):
				now = time.time()
				await db.execute('INSERT OR REPLACE INTO lb_map VALUES (?, ?)', (form['key'], tconst))
				for section in rows[0]['sections'].split(','):
					if section in ('watched', 'watchlist'):
						await db.execute('INSERT OR IGNORE INTO marks VALUES (?, ?, ?, ?)', (g.user['id'], tconst, section, now))
				if rows[0]['rating']:
					await db.execute('INSERT OR IGNORE INTO ratings VALUES (?, ?, ?, ?, ?)', (g.user['id'], 'tt', tconst, rows[0]['rating'], now))
			await db.execute('DELETE FROM lb_unmatched WHERE user_id = ? AND key = ?', (g.user['id'], form['key']))
			await db.commit()

		return ''

	async with user_db() as db:
		items = await db.execute_fetchall('SELECT * FROM lb_unmatched WHERE user_id = ? ORDER BY name', (g.user['id'],))

	candidates = {}

	for item in items:
		match = re.match(r'^(.*?)(?: \((\d{4})\))?$', item['name'])
		fts   = fts_query(match.group(1))
		rows  = await search_titles(fts, 8) if fts else []
		year  = int(match.group(2)) if match.group(2) else None
		candidates[item['key']] = sorted(rows, key=lambda r: (abs((r['start_year'] or 0) - year) if year else 0, -(r['votes'] or 0)))[:6]

	return await render_template('lb_fix.html', items=items, candidates=candidates)


@app.route('/letterboxd/fix/search')
@require()
async def lb_fix_search():
	'''Return candidate titles for a manual Letterboxd match search.'''

	fts = fts_query(request.args.get('q', ''))

	return await render_template('_fix_candidates.html', key=request.args.get('key', ''), rows=await search_titles(fts, 8) if fts else [])


@app.route('/letterboxd/import', methods=['POST'])
@require()
async def lb_import():
	'''Start importing an uploaded Letterboxd export zip and return the sync status partial.'''

	upload = (await request.files).get('export')

	if upload and not state['lb'].get(g.user['id'], {}).get('running'):
		spawn(letterboxd_import(g.user['id'], upload.read()))
		await asyncio.sleep(0.3)

	return await lb_status()


@app.route('/letterboxd/sync', methods=['GET', 'POST'])
@require()
async def lb_sync():
	'''Start a Letterboxd sync (POST) and return the sync status partial.'''

	if request.method == 'POST' and not state['lb'].get(g.user['id'], {}).get('running'):
		spawn(letterboxd_sync(g.user['id']))
		await asyncio.sleep(0.3)

	return await lb_status()


@app.route('/library')
@require()
async def library():
	'''Watchlist, watched, and rated titles/people.'''

	tab  = request.args.get('tab', 'watchlist')
	sort = request.args.get('sort', 'added')
	page = max(1, request.args.get('page', 1, type=int))
	rows = await library_rows(tab, sort)
	size = 96

	async with user_db() as db:
		counts = (await db.execute_fetchall("SELECT (SELECT count(*) FROM marks WHERE user_id = :u AND mark = 'watched') AS watched, (SELECT count(*) FROM marks WHERE user_id = :u AND mark = 'watchlist') AS watchlist, (SELECT count(*) FROM ratings WHERE user_id = :u AND kind = 'tt') AS rated, (SELECT count(*) FROM ratings WHERE user_id = :u AND kind = 'nm') AS people, (SELECT avg(rating) FROM ratings WHERE user_id = :u AND kind = 'tt') AS avg", {'u': g.user['id']}))[0]
		histo  = {r['rating']: r['count'] for r in await db.execute_fetchall("SELECT rating, count(*) AS count FROM ratings WHERE user_id = ? AND kind = ? GROUP BY rating", (g.user['id'], 'nm' if tab == 'people' else 'tt'))}

	return await render_template('library.html', tab=tab, sort=sort, rows=rows[(page - 1) * size:page * size], total=len(rows), page=page, has_next=len(rows) > page * size, counts=counts, histo=histo, stars=request.args.get('stars', type=int), services=request.args.get('services') == '1')


@app.route('/library/export.<fmt>')
@require()
async def library_export(fmt: str):
	'''
	Export a library tab as CSV or JSON.

	:param fmt: 'csv' or 'json'
	'''

	tab = request.args.get('tab', 'watchlist')

	if fmt not in ('csv', 'json'):
		abort(404)

	if tab == 'people':
		data = [{'imdb_id': fmt_id('nm', r['nconst']), 'name': r['name'], 'my_rating': r['my_rating'] / 2} for r in await library_rows(tab, 'mine')]
	else:
		data = [{'imdb_id': fmt_id('tt', r['tconst']), 'title': r['primary_title'], 'year': r['start_year'], 'type': r['type'], 'imdb_rating': r['rating'], 'my_rating': r['my_rating'] / 2 if r['my_rating'] else None, 'watched': r['watched'], 'watchlist': r['watchlist']} for r in await library_rows(tab, 'added')]

	if fmt == 'json':
		body = json.dumps(data, indent=2, ensure_ascii=False)
	else:
		buffer = io.StringIO()
		writer = csv.DictWriter(buffer, fieldnames=list(data[0]) if data else ['imdb_id'])
		writer.writeheader()
		writer.writerows(data)
		body = buffer.getvalue()

	return Response(body, mimetype='application/json' if fmt == 'json' else 'text/csv', headers={'Content-Disposition': f'attachment; filename={tab}.{fmt}'})


async def library_rows(tab: str, sort: str) -> list:
	'''
	Return the rows for a library tab.

	:param tab: 'watchlist', 'watched', 'ratings', or 'people'
	:param sort: Sort key
	'''

	stars    = request.args.get('stars', type=int)
	services = await my_providers() if request.args.get('services') == '1' else []
	uid      = g.user['id']

	if tab == 'people':
		return await query(f"SELECT n.*, r.rating AS my_rating FROM u.ratings r JOIN names n ON n.nconst = r.id WHERE r.user_id = {uid} AND r.kind = 'nm' {'AND r.rating = ?' if stars else ''} ORDER BY r.rating DESC, n.score DESC", (stars,) if stars else ())

	source = {'watchlist': f"SELECT tconst, added FROM u.marks WHERE user_id = {uid} AND mark = 'watchlist'", 'watched': f"SELECT tconst, added FROM u.marks WHERE user_id = {uid} AND mark = 'watched'"}.get(tab, f"SELECT id AS tconst, updated AS added FROM u.ratings WHERE user_id = {uid} AND kind = 'tt' {'AND rating = ?' if stars else ''}")
	order  = {'added': 'm.added DESC', 'rating': 't.rating DESC', 'mine': 'my_rating DESC', 'year': 't.start_year DESC', 'title': 't.primary_title COLLATE NOCASE'}.get(sort, 'm.added DESC')
	extra  = f'WHERE t.tconst IN (SELECT tconst FROM u.title_providers WHERE provider_id IN ({",".join("?" * len(services))}))' if services else ''

	return await query(f'''
		SELECT t.*, m.added, r.rating AS my_rating,
			EXISTS (SELECT 1 FROM u.marks w WHERE w.user_id = {uid} AND w.tconst = t.tconst AND w.mark = 'watched') AS watched,
			EXISTS (SELECT 1 FROM u.marks w WHERE w.user_id = {uid} AND w.tconst = t.tconst AND w.mark = 'watchlist') AS watchlist
		FROM ({source}) m JOIN titles t ON t.tconst = m.tconst LEFT JOIN u.ratings r ON r.user_id = {uid} AND r.kind = 'tt' AND r.id = t.tconst
		{extra}
		ORDER BY {order}, t.votes DESC
	''', ((stars,) if stars and tab == 'ratings' else ()) + tuple(services))


@app.route('/list/<int:list_id>')
@require()
async def list_view(list_id: int):
	'''
	Show a list's titles.

	:param list_id: List id
	'''

	sort = request.args.get('sort', 'added')

	async with user_db() as db:
		rows  = await db.execute_fetchall('SELECT * FROM lists WHERE id = ? AND user_id = ?', (list_id, g.user['id']))
		items = await db.execute_fetchall('SELECT tconst, added FROM list_items WHERE list_id = ? ORDER BY added DESC', (list_id,)) if rows else []

	if not rows:
		abort(404)

	titles = await titles_by_ids([item['tconst'] for item in items])
	titles = [titles[item['tconst']] for item in items if item['tconst'] in titles]

	if sort in ('rating', 'votes'):
		titles.sort(key=lambda t: t[sort] or 0, reverse=True)
	elif sort == 'year':
		titles.sort(key=lambda t: t['start_year'] or 0, reverse=True)
	elif sort == 'title':
		titles.sort(key=lambda t: t['primary_title'].lower())

	return await render_template('list.html', lst=rows[0], titles=titles, sort=sort)


@app.route('/list/<int:list_id>/delete', methods=['POST'])
@require()
async def list_delete(list_id: int):
	'''
	Delete a list.

	:param list_id: List id
	'''

	async with user_db() as db:
		await db.execute('PRAGMA foreign_keys = ON')
		await db.execute('DELETE FROM lists WHERE id = ? AND user_id = ?', (list_id, g.user['id']))
		await db.commit()

	return redirect('/lists')


@app.route('/list/<int:list_id>/edit', methods=['POST'])
@require()
async def list_edit(list_id: int):
	'''
	Rename a list or change its description.

	:param list_id: List id
	'''

	form = await request.form

	async with user_db() as db:
		await db.execute('UPDATE lists SET name = ?, description = ?, updated = ? WHERE id = ? AND user_id = ?', (form['name'].strip() or 'Untitled', form.get('description', '').strip(), time.time(), list_id, g.user['id']))
		await db.commit()

	return redirect(f'/list/{list_id}')


@app.route('/list/<int:list_id>/export.<fmt>')
@require()
async def list_export(list_id: int, fmt: str):
	'''
	Export a list as CSV or JSON.

	:param list_id: List id
	:param fmt: 'csv' or 'json'
	'''

	async with user_db() as db:
		rows  = await db.execute_fetchall('SELECT name FROM lists WHERE id = ? AND user_id = ?', (list_id, g.user['id']))
		items = await db.execute_fetchall('SELECT tconst, added FROM list_items WHERE list_id = ? ORDER BY added', (list_id,)) if rows else []

	if not rows or fmt not in ('csv', 'json'):
		abort(404)

	titles = await titles_by_ids([item['tconst'] for item in items])
	data   = [{'imdb_id': fmt_id('tt', t['tconst']), 'title': t['primary_title'], 'year': t['start_year'], 'type': t['type'], 'rating': t['rating'], 'votes': t['votes'], 'url': f'https://www.imdb.com/title/{fmt_id("tt", t["tconst"])}/'} for t in (titles[i['tconst']] for i in items if i['tconst'] in titles)]
	name   = re.sub(r'\W+', '_', rows[0]['name']).strip('_') or 'list'

	if fmt == 'json':
		body = json.dumps(data, indent=2, ensure_ascii=False)
	else:
		buffer = io.StringIO()
		writer = csv.DictWriter(buffer, fieldnames=['imdb_id', 'title', 'year', 'type', 'rating', 'votes', 'url'])
		writer.writeheader()
		writer.writerows(data)
		body = buffer.getvalue()

	return Response(body, mimetype='application/json' if fmt == 'json' else 'text/csv', headers={'Content-Disposition': f'attachment; filename={name}.{fmt}'})


@app.route('/lists', methods=['GET', 'POST'])
@require()
async def lists():
	'''Show all lists, or create a new one.'''

	if request.method == 'POST':
		form = await request.form
		now  = time.time()

		async with user_db() as db:
			cursor = await db.execute('INSERT INTO lists (name, description, created, updated, user_id) VALUES (?, ?, ?, ?, ?)', (form['name'].strip() or 'Untitled', form.get('description', '').strip(), now, now, g.user['id']))
			if form.get('tconst'):
				await db.execute('INSERT INTO list_items VALUES (?, ?, ?)', (cursor.lastrowid, int(form['tconst']), now))
			await db.commit()

		if form.get('tconst'):
			return await title_lists(int(form['tconst']))

		return redirect(f'/list/{cursor.lastrowid}')

	return await render_template('lists.html', lists=await list_summaries())


@app.route('/login', methods=['GET', 'POST'])
async def login():
	'''Log in (POST checks the password and starts a 1 year session).'''

	error = None
	name  = ''
	dest  = request.args.get('next', '/')

	if request.method == 'POST':
		form = await request.form
		name = form.get('name', '').strip()
		dest = form.get('next', '/')

		async with user_db() as db:
			rows = await db.execute_fetchall('SELECT * FROM users WHERE name = ?', (name,))

		if not rows or not await asyncio.to_thread(password_check, form.get('password', ''), rows[0]['password']):
			error = 'Wrong username or password'
		elif not rows[0]['approved']:
			error = 'Your account is waiting for admin approval'
		else:
			token = secrets.token_urlsafe(32)
			async with user_db() as db:
				await db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
				await db.execute('INSERT INTO sessions VALUES (?, ?, ?)', (hashlib.sha256(token.encode()).hexdigest(), rows[0]['id'], time.time() + SESSION_AGE))
				await db.commit()
			response = redirect(dest if dest.startswith('/') and not dest.startswith('//') else '/')
			response.set_cookie('session', token, max_age=SESSION_AGE, httponly=True, samesite='Lax')
			return response

	return await render_template('login.html', error=error, name=name, next=dest)


@app.route('/logout', methods=['POST'])
async def logout():
	'''End the current session.'''

	if token := request.cookies.get('session'):
		async with user_db() as db:
			await db.execute('DELETE FROM sessions WHERE token = ?', (hashlib.sha256(token.encode()).hexdigest(),))
			await db.commit()

	response = redirect('/')
	response.delete_cookie('session')

	return response


@app.route('/name/nm<int:nconst>')
async def name(nconst: int):
	'''
	Person detail page with filmography.

	:param nconst: Numeric person id
	'''

	rows = await query('SELECT * FROM names WHERE nconst = ?', (nconst,))

	if not rows:
		abort(404)

	person  = rows[0]
	credits = await query('''
		SELECT t.*, p.category, p.job, p.characters FROM principals p JOIN titles t ON t.tconst = p.tconst WHERE p.nconst = ?
		UNION ALL
		SELECT t.*, c.role, NULL, NULL FROM crew c JOIN titles t ON t.tconst = c.tconst WHERE c.nconst = ? AND NOT EXISTS (SELECT 1 FROM principals p WHERE p.tconst = c.tconst AND p.nconst = c.nconst AND p.category = c.role)
		ORDER BY start_year DESC
	''', (nconst, nconst))
	groups = {}

	for row in credits:
		groups.setdefault(row['category'], []).append(row)

	known = [int(t[2:]) for t in (person['known_for'] or '').split(',') if t]
	known = await titles_by_ids(known)

	return await render_template('name.html', person=person, groups=sorted(groups.items(), key=lambda g: -len(g[1])), known=list(known.values()))


@app.route('/name/nm<int:nconst>/follow', methods=['POST'])
@require()
async def name_follow(nconst: int):
	'''
	Toggle following a person for the Upcoming page.

	:param nconst: Numeric person id
	'''

	async with user_db() as db:
		cursor = await db.execute('DELETE FROM follows WHERE user_id = ? AND nconst = ?', (g.user['id'], nconst))
		if not cursor.rowcount:
			await db.execute('INSERT INTO follows VALUES (?, ?, ?)', (g.user['id'], nconst, time.time()))
		await db.commit()

	return await render_template('_follow.html', nconst=nconst)


@app.route('/name/nm<int:nconst>/tmdb')
async def name_tmdb(nconst: int):
	'''
	Render the TMDB enrichment partial for a person.

	:param nconst: Numeric person id
	'''

	return await render_template('_tmdb_name.html', d=await tmdb_details(fmt_id('nm', nconst)))


@app.route('/names')
async def names():
	'''Browse and search people.'''

	q          = request.args.get('q', '').strip()
	profession = request.args.get('profession', '')
	sort       = request.args.get('sort', 'score')
	page       = max(1, request.args.get('page', 1, type=int))
	where      = []
	params     = []

	if q and (fts := fts_query(q)):
		where.append('nconst IN (SELECT rowid FROM names_fts WHERE names_fts MATCH ?)')
		params.append(fts)

	if profession:
		where.append("(',' || professions || ',') LIKE ?")
		params.append(f'%,{profession},%')

	sql  = f'SELECT * FROM names {"WHERE " + " AND ".join(where) if where else ""} ORDER BY {NAME_SORTS.get(sort, NAME_SORTS["score"])} LIMIT ? OFFSET ?'
	rows = await query(sql, params + [PAGE_SIZE + 1, (page - 1) * PAGE_SIZE])

	return await render_template('names.html', people=rows[:PAGE_SIZE], has_next=len(rows) > PAGE_SIZE, page=page, q=q, profession=profession, sort=sort, sorts=NAME_SORTS)


@app.route('/poster/<imdb_id>')
async def poster(imdb_id: str):
	'''
	Serve a poster/headshot from local storage, downloading it from TMDB or Letterboxd on first request.

	:param imdb_id: IMDb id (tt... or nm...)
	'''

	if not re.fullmatch(r'(tt|nm)\d+', imdb_id):
		abort(404)

	if path := await ensure_poster(imdb_id):
		return await send_file(path, mimetype='image/jpeg', cache_timeout=30 * 86400)

	return Response(NO_COVER if imdb_id.startswith('tt') else NO_PHOTO, mimetype='image/svg+xml', headers={'Cache-Control': 'max-age=3600'})


@app.route('/precache', methods=['GET', 'POST'])
@require(admin=True)
async def precache_route():
	'''Start the offline pre-cache (POST) and return its status partial.'''

	if request.method == 'POST' and not state['precache'].get('running'):
		spawn(precache())
		await asyncio.sleep(0.3)

	return await render_template('_precache.html', p=state['precache'], last=float(await setting('precache_last', '0')))


@app.route('/rate/<kind>/<int:item_id>', methods=['POST'])
@require()
async def rate(kind: str, item_id: int):
	'''
	Set, change, or clear (same value again) the user's rating for a title or person.

	:param kind: 'tt' or 'nm'
	:param item_id: Numeric id
	'''

	if kind not in ('tt', 'nm'):
		abort(404)

	value = (await request.form).get('rating', type=int)

	async with user_db() as db:
		current = await db.execute_fetchall('SELECT rating FROM ratings WHERE user_id = ? AND kind = ? AND id = ?', (g.user['id'], kind, item_id))
		if not value or not 1 <= value <= 10 or (current and current[0]['rating'] == value):
			await db.execute('DELETE FROM ratings WHERE user_id = ? AND kind = ? AND id = ?', (g.user['id'], kind, item_id))
		else:
			await db.execute('INSERT OR REPLACE INTO ratings VALUES (?, ?, ?, ?, ?)', (g.user['id'], kind, item_id, value, time.time()))
		await db.commit()

	return await render_template('_stars.html', kind=kind, item_id=item_id)


@app.route('/recommend')
@require()
async def recommend():
	'''Recommendations derived from ratings, watched, watchlist, a list, or a single title.'''

	source = request.args.get('source', 'ratings')
	stars  = request.args.get('min', 8, type=int)
	kind   = request.args.get('kind', 'all')
	seeds  = {}
	label  = ''

	async with user_db() as db:
		all_lists = await db.execute_fetchall('SELECT id, name FROM lists WHERE user_id = ? ORDER BY name', (g.user['id'],))
		if source == 'ratings':
			seeds = {r['id']: r['rating'] - 5 for r in await db.execute_fetchall("SELECT id, rating FROM ratings WHERE user_id = ? AND kind = 'tt' AND rating >= ?", (g.user['id'], stars))}
		elif source in ('watched', 'watchlist'):
			seeds = {r['tconst']: 1 for r in await db.execute_fetchall('SELECT tconst FROM marks WHERE user_id = ? AND mark = ? ORDER BY added DESC LIMIT 200', (g.user['id'], source))}
		elif source.startswith('list:') and source[5:].isdigit():
			seeds = {r['tconst']: 1 for r in await db.execute_fetchall('SELECT i.tconst FROM list_items i JOIN lists l ON l.id = i.list_id WHERE l.id = ? AND l.user_id = ?', (int(source[5:]), g.user['id']))}
		elif source.startswith('title:') and source[6:].isdigit():
			seeds = {int(source[6:]): 1}
			label = (await titles_by_ids([int(source[6:])])).get(int(source[6:]), {'primary_title': ''})['primary_title']

	results = await recommend_titles(seeds, 120) if seeds else []

	if kind == 'movies':
		results = [r for r in results if r['t']['type'] in ('movie', 'tvMovie')]
	elif kind == 'tv':
		results = [r for r in results if r['t']['type'] in ('tvSeries', 'tvMiniSeries')]

	if request.args.get('services') == '1' and (services := await my_providers()):
		async with user_db() as db:
			streamable = {r['tconst'] for r in await db.execute_fetchall(f'SELECT tconst FROM title_providers WHERE provider_id IN ({",".join("?" * len(services))})', services)}
		results = [r for r in results if r['t']['tconst'] in streamable]

	return await render_template('recommend.html', results=results[:60], source=source, stars=stars, kind=kind, lists=all_lists, seeds=len(seeds), label=label, services=request.args.get('services') == '1')


@app.route('/register', methods=['GET', 'POST'])
async def register():
	'''Sign up for an account (POST checks the captcha and creates it, pending approval when that is turned on).'''

	closed = await setting('registration', 'open') != 'open'
	error  = None
	name   = ''
	done   = None

	if request.method == 'POST' and not closed:
		form     = await request.form
		name     = form.get('name', '').strip()
		password = form.get('password', '')
		answer   = state['captchas'].pop(form.get('captcha_id', ''), None)

		if not answer or answer[1] < time.time() or form.get('captcha', '').strip().upper() != answer[0]:
			error = 'Wrong captcha, try this new one'
		elif not re.fullmatch(r'[A-Za-z]{3,15}', name):
			error = 'Username must be 3 to 15 letters (A-Z only)'
		elif not 6 <= len(password) <= 100:
			error = 'Password must be 6 to 100 characters'
		else:
			approved = await setting('approval', '1') != '1'
			try:
				async with user_db() as db:
					await db.execute('INSERT INTO users (name, password, admin, approved, created) VALUES (?, ?, 0, ?, ?)', (name, await asyncio.to_thread(password_hash, password), int(approved), time.time()))
					await db.commit()
				done = 'approved' if approved else 'pending'
			except sqlite3.IntegrityError:
				error = 'That username is taken'

	return await render_template('register.html', closed=closed, error=error, name=name, done=done, captcha=None if closed or done else captcha_new())


@app.route('/search')
async def search():
	'''Global search across titles and people; returns a dropdown partial for htmx requests.'''

	q     = request.args.get('q', '').strip()
	fts   = fts_query(q)
	full  = 'HX-Request' not in request.headers or request.headers.get('HX-Boosted')
	kind  = request.args.get('kind', 'all') if full else 'all'
	noimg = full and request.args.get('noimg') == '1'

	if not fts:
		return await render_template('search.html' if full else '_quick.html', q=q, titles=[], people=[], episodes=[], kind=kind, noimg=noimg)

	limit    = 30 if full else 6
	types    = {'movies': ('movie', 'tvMovie'), 'tv': ('tvSeries', 'tvMiniSeries')}.get(kind, ())
	titles   = await search_titles(fts, limit, types=types) if kind != 'people' else []
	people   = await query('SELECT n.* FROM names_fts f JOIN names n ON n.nconst = f.rowid WHERE names_fts MATCH ? ORDER BY n.score DESC LIMIT ?', (fts, limit)) if kind in ('all', 'people') else []
	episodes = await search_titles(fts, limit, episodes=True) if full and kind in ('all', 'tv') else []

	if noimg:
		found  = await asyncio.gather(*(ensure_poster(fmt_id('tt', t['tconst'])) for t in titles), *(ensure_poster(fmt_id('nm', p['nconst'])) for p in people))
		people = [p for p, path in zip(people, found[len(titles):]) if path]
		titles = [t for t, path in zip(titles, found) if path]

	return await render_template('search.html' if full else '_quick.html', q=q, titles=titles, people=people, episodes=episodes, kind=kind, noimg=noimg)


@app.route('/settings', methods=['GET', 'POST'])
@require()
async def settings():
	'''View and change the account's settings.'''

	uid = g.user['id']

	if request.method == 'POST':
		form = await request.form

		async with user_db() as db:
			if 'letterboxd_user' in form:
				await db.execute('INSERT OR REPLACE INTO user_settings VALUES (?, ?, ?)', (uid, 'letterboxd_user', form['letterboxd_user'].strip()))
			if form.get('providers_form'):
				await db.execute('INSERT OR REPLACE INTO user_settings VALUES (?, ?, ?)', (uid, 'providers', json.dumps([int(p) for p in form.getlist('provider')])))
			if 'subdl_key' in form:
				await db.execute('INSERT OR REPLACE INTO subtitle_keys VALUES (?, ?, ?, ?, ?)', (uid, *(form.get(key, '').strip() for key in ('subdl_key', 'os_key', 'os_user', 'os_pass'))))
				state['os_tokens'].pop(f'os:{uid}', None)
			if 'bm_url' in form:
				if (bm_url := form['bm_url'].strip().rstrip('/')) and not valid_https_url(bm_url):
					return redirect('/settings?bm=invalid')
				await db.execute('INSERT OR REPLACE INTO user_settings VALUES (?, ?, ?)', (uid, 'bm_url', bm_url))
			await db.commit()

		return redirect('/settings')

	async with user_db() as db:
		keys = await db.execute_fetchall('SELECT * FROM subtitle_keys WHERE user_id = ?', (uid,))

	providers = await tmdb_cached('providers:US', 'watch/providers/movie', 30 * 86400, {'watch_region': 'US'})
	providers = sorted((providers or {}).get('results', []), key=lambda p: p.get('display_priorities', {}).get('US', 999))
	subs      = dict(keys[0]) if keys else {'subdl_key': '', 'os_key': '', 'os_user': '', 'os_pass': ''}
	page      = {'letterboxd_user': await user_setting('letterboxd_user'), 'providers': providers, 'selected': set(await my_providers()), 'subs': subs, 'account': request.args.get('account'), 'bm_url': await user_setting('bm_url'), 'bm_error': request.args.get('bm') == 'invalid'}

	if g.user['admin']:
		subs['files'] = sum(1 for _ in SUBS_DIR.rglob('*.srt')) if SUBS_DIR.exists() else 0

	return await render_template('settings.html', **page)


@app.route('/title/tt<int:tconst>')
async def title(tconst: int):
	'''
	Title detail page.

	:param tconst: Numeric title id
	'''

	rows = await query('SELECT * FROM titles WHERE tconst = ?', (tconst,))

	if not rows:
		abort(404)

	cast    = await query('SELECT p.*, n.name FROM principals p JOIN names n ON n.nconst = p.nconst WHERE p.tconst = ? ORDER BY p.ordering', (tconst,))
	crew    = await query('SELECT c.role, n.nconst, n.name FROM crew c JOIN names n ON n.nconst = c.nconst WHERE c.tconst = ?', (tconst,))
	akas    = await query('SELECT DISTINCT title, region FROM akas WHERE tconst = ? AND title != ?', (tconst, rows[0]['primary_title']))
	parent  = await query('SELECT e.season, e.episode, t.* FROM episodes e JOIN titles t ON t.tconst = e.parent WHERE e.tconst = ?', (tconst,))
	seasons = {}

	if rows[0]['type'] in ('tvSeries', 'tvMiniSeries'):
		for ep in await query('SELECT e.season, e.episode, t.* FROM episodes e JOIN titles t ON t.tconst = e.tconst WHERE e.parent = ? ORDER BY e.season IS NULL, e.season, e.episode', (tconst,)):
			seasons.setdefault(ep['season'], []).append(ep)

	return await render_template('title.html', t=rows[0], cast=[c for c in cast if c['category'] not in ('director', 'writer')], crew=crew, akas=akas, parent=parent[0] if parent else None, seasons=seasons, lists_html=await title_lists(tconst) if g.user else '')


@app.route('/title/tt<int:tconst>/mark', methods=['POST'])
@require()
async def title_mark(tconst: int):
	'''
	Toggle watched/watchlist for a title; marking watched removes it from the watchlist.

	:param tconst: Numeric title id
	'''

	mark = (await request.form).get('mark')

	if mark not in ('watched', 'watchlist'):
		abort(400)

	async with user_db() as db:
		cursor = await db.execute('DELETE FROM marks WHERE user_id = ? AND tconst = ? AND mark = ?', (g.user['id'], tconst, mark))
		if not cursor.rowcount:
			await db.execute('INSERT INTO marks VALUES (?, ?, ?, ?)', (g.user['id'], tconst, mark, time.time()))
			if mark == 'watched':
				await db.execute("DELETE FROM marks WHERE user_id = ? AND tconst = ? AND mark = 'watchlist'", (g.user['id'], tconst))
		await db.commit()

	return await render_template('_marks.html', tconst=tconst)


@app.route('/title/tt<int:tconst>/lists', methods=['GET', 'POST'])
@require()
async def title_lists(tconst: int) -> str:
	'''
	Render (and on POST toggle) a title's list memberships.

	:param tconst: Numeric title id
	'''

	if request.method == 'POST' and (form := await request.form).get('list_id'):
		list_id = int(form['list_id'])

		async with user_db() as db:
			if await db.execute_fetchall('SELECT 1 FROM lists WHERE id = ? AND user_id = ?', (list_id, g.user['id'])):
				cursor = await db.execute('DELETE FROM list_items WHERE list_id = ? AND tconst = ?', (list_id, tconst))
				if not cursor.rowcount:
					await db.execute('INSERT INTO list_items VALUES (?, ?, ?)', (list_id, tconst, time.time()))
				await db.execute('UPDATE lists SET updated = ? WHERE id = ?', (time.time(), list_id))
				await db.commit()

	async with user_db() as db:
		member = {row['list_id'] for row in await db.execute_fetchall('SELECT i.list_id FROM list_items i JOIN lists l ON l.id = i.list_id WHERE i.tconst = ? AND l.user_id = ?', (tconst, g.user['id']))}

	return await render_template('_lists.html', tconst=tconst, lists=await list_summaries(), member=member)


@app.route('/subs', methods=['GET', 'POST'])
@require(admin=True)
async def subs_route():
	'''Start the subtitle prefetch (POST) and return its status partial.'''

	if request.method == 'POST' and not state['subs'].get('running'):
		spawn(subtitle_prefetch())
		await asyncio.sleep(0.3)

	async with user_db() as db:
		empty = {r[0] for r in await db.execute_fetchall("SELECT tconst FROM subtitles WHERE data = '[]'")}

	library = [r['tconst'] for r in await query("SELECT tconst FROM titles WHERE tconst IN (SELECT tconst FROM u.marks UNION SELECT tconst FROM u.list_items) AND type NOT IN ('tvSeries', 'tvMiniSeries')")]
	saved   = {int(d.name[2:]) for d in SUBS_DIR.iterdir() if any(d.glob('*.srt'))} if SUBS_DIR.exists() else set()
	quota   = state['subs']['quota'] if state['subs'].get('running') else await subtitle_quota()
	daily   = quota['subdl']['limit'] + quota['os']['limit']
	stats   = {'total': len(library), 'saved': len(saved & set(library)), 'none': len(empty & set(library) - saved)}
	stats  |= {'left': stats['total'] - stats['saved'] - stats['none'], 'days': -(-(stats['total'] - stats['saved'] - stats['none']) // daily) if daily else None}

	return await render_template('_subs_status.html', s=state['subs'], last=float(await setting('subs_last', '0')), done=state['subs'].get('done', await setting('subs_done')), quota=quota, stats=stats)


@app.route('/title/tt<int:tconst>/subs', methods=['GET', 'POST'])
@require()
async def title_subs(tconst: int):
	'''
	Render a title's subtitles: downloaded files plus cached search results. ?search=1 searches the providers, POST downloads one.

	:param tconst: Numeric title id
	'''

	error = None

	try:
		if request.method == 'POST':
			form = await request.form
			await subtitle_download(tconst, form['provider'], form['id'], form['release'])
		elif request.args.get('search'):
			await subtitle_search(tconst)
	except RuntimeError as e:
		error = str(e)

	async with user_db() as db:
		rows = await db.execute_fetchall('SELECT data, fetched FROM subtitles WHERE tconst = ?', (tconst,))

	results = json.loads(rows[0]['data']) if rows else None
	files   = subtitle_files(tconst)

	for r in results or []:
		r['file'] = subtitle_name(r['release'])

	return await render_template('_subs.html', tconst=tconst, files=files, results=results, fetched=rows[0]['fetched'] if rows else None, error=error, keys=bool(await subtitle_accounts()))


@app.route('/title/tt<int:tconst>/subs/<filename>')
@require()
async def title_subs_file(tconst: int, filename: str):
	'''
	Serve a downloaded subtitle file.

	:param tconst: Numeric title id
	:param filename: File name from subtitle_files()
	'''

	if filename not in subtitle_files(tconst):
		abort(404)

	return await send_file(SUBS_DIR / fmt_id('tt', tconst) / filename, mimetype='application/x-subrip', as_attachment=True, attachment_filename=filename)


@app.route('/title/tt<int:tconst>/tmdb')
async def title_tmdb(tconst: int):
	'''
	Render the TMDB enrichment partial for a title.

	:param tconst: Numeric title id
	'''

	d = await tmdb_details(fmt_id('tt', tconst))

	return await render_template('_tmdb_title.html', d=d, tconst=tconst, streams=await stream_links(tconst, d), torrents=bool(g.user and await user_setting('bm_url') or await setting('bm_url')))


@app.route('/title/tt<int:tconst>/torrents')
async def title_torrents(tconst: int):
	'''
	Render the top torrents for a title from bitmagnet.

	:param tconst: Numeric title id
	'''

	try:
		torrents, total, search = await torrent_search(tconst)
	except RuntimeError as e:
		return await render_template('_torrents.html', torrents=[], total=0, search=None, error=str(e))

	return await render_template('_torrents.html', torrents=torrents, total=total, search=search, error=None)


@app.route('/titles')
async def titles():
	'''Browse titles with filters.'''

	args   = request.args
	sort   = args.get('sort', 'votes')
	page   = max(1, args.get('page', 1, type=int))
	where  = []
	params = []

	if q := fts_query(args.get('q', '')):
		where.append(f'tconst IN (SELECT rowid FROM {"episodes_fts" if args.get("type") == "tvEpisode" else "titles_fts"} WHERE {"episodes_fts" if args.get("type") == "tvEpisode" else "titles_fts"} MATCH ?)')
		params.append(q)

	if args.get('type') in TITLE_TYPES:
		where.append('type = ?')
		params.append(args['type'])
	else:
		where.append("type != 'tvEpisode'")

	for genre in args.getlist('genre'):
		if genre in GENRES:
			where.append("(',' || genres || ',') LIKE ?")
			params.append(f'%,{genre},%')

	for field, column, op in (('year_from', 'start_year', '>='), ('year_to', 'start_year', '<='), ('rating', 'rating', '>='), ('votes', 'votes', '>=')):
		if value := args.get(field, type=float):
			where.append(f'{column} {op} ?')
			params.append(value)

	if sort == 'rating' and not args.get('votes'):
		where.append('votes >= 1000')

	if not g.user and sort == 'mine':
		sort = 'votes'

	if g.user and args.get('mine') in MINE_FILTERS:
		where.append(MINE_FILTERS[args['mine']].format(uid=g.user['id']))

	if sort == 'mine':
		where.append(MINE_FILTERS['rated'].format(uid=g.user['id']))

	if args.get('services') == '1' and (services := await my_providers()):
		where.append(f'tconst IN (SELECT tconst FROM u.title_providers WHERE provider_id IN ({",".join("?" * len(services))}))')
		params.extend(services)

	sql  = f'SELECT * FROM titles WHERE {" AND ".join(where)} ORDER BY {TITLE_SORTS.get(sort, TITLE_SORTS["votes"]).format(uid=g.user["id"] if g.user else 0)} LIMIT ? OFFSET ?'
	rows = await query(sql, params + [PAGE_SIZE + 1, (page - 1) * PAGE_SIZE])

	return await render_template('titles.html', titles=rows[:PAGE_SIZE], has_next=len(rows) > PAGE_SIZE, page=page, args=args, sort=sort, sorts=TITLE_SORTS, types=TITLE_TYPES, genres=GENRES)


@app.route('/upcoming')
@require()
async def upcoming():
	'''Upcoming and recent releases from followed people.'''

	async with user_db() as db:
		follows = [r['nconst'] for r in await db.execute_fetchall('SELECT nconst FROM follows WHERE user_id = ? ORDER BY added DESC', (g.user['id'],))]

	people  = {row['nconst']: row for row in await query(f'SELECT * FROM names WHERE nconst IN ({",".join("?" * len(follows))})', follows)} if follows else {}
	today   = time.strftime('%Y-%m-%d')
	cutoff  = time.strftime('%Y-%m-%d', time.localtime(time.time() - 120 * 86400))
	merged  = {}
	details = await asyncio.gather(*(tmdb_details(fmt_id('nm', n)) for n in follows))

	for nconst, person in zip(follows, details):
		if not person or not person.get('tmdb_id'):
			continue
		credits = await tmdb_cached(f'credits:{fmt_id("nm", nconst)}', f'person/{person["tmdb_id"]}/combined_credits', 86400) or {}
		for role, items in (('cast', credits.get('cast', [])), ('crew', credits.get('crew', []))):
			for item in items:
				if role == 'crew' and item.get('job') not in ('Director', 'Writer', 'Screenplay', 'Creator'):
					continue
				date = item.get('release_date') or item.get('first_air_date') or ''
				if date and date < cutoff:
					continue
				if item.get('media_type') == 'tv' and role == 'cast' and not date:
					continue
				entry = merged.setdefault((item['media_type'], item['id']), {'kind': item['media_type'], 'id': item['id'], 'title': item.get('title') or item.get('name'), 'date': date, 'poster': item.get('poster_path'), 'overview': item.get('overview'), 'people': []})
				who   = f'{people[nconst]["name"] if nconst in people else "?"} ({item.get("job") or ("as " + item["character"] if item.get("character") else "cast")})'
				if who not in entry['people']:
					entry['people'].append(who)

	items = sorted(merged.values(), key=lambda e: e['date'] or '9999')

	return await render_template('upcoming.html', upcoming=[e for e in items if not e['date'] or e['date'] > today], recent=[e for e in reversed(items) if e['date'] and e['date'] <= today], follows=[people[n] for n in follows if n in people])


@app.route('/update', methods=['GET', 'POST'])
async def update():
	'''Start the importer (POST, admin only) and return the status partial (public, for the building page).'''

	if request.method == 'POST' and not (g.user and g.user['admin']):
		abort(403)

	if request.method == 'POST' and read_status().get('state') != 'running':
		await start_import()
		await asyncio.sleep(0.5)

	return await render_template('_status.html')



if __name__ == '__main__':
	load_env()

	config      = Config()
	config.bind = [f'{os.environ.get("HOST", "0.0.0.0")}:{os.environ.get("PORT", "5000")}']

	asyncio.run(serve(app, config))
