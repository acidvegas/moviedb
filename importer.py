#!/usr/bin/env python3
# IMDb Dataset Importer - developed by acidvegas (https://github.com/acidvegas)

import gzip
import json
import os
import sqlite3
import time
import urllib.request

from pathlib import Path


BASE_DIR     = Path(__file__).resolve().parent
DATA_DIR     = BASE_DIR / 'data'
DB_PATH      = BASE_DIR / 'imdb.db'
STATUS_PATH  = DATA_DIR / 'status.json'
DATASET_URL  = 'https://datasets.imdbws.com'
DATASETS     = ['title.basics', 'title.ratings', 'title.episode', 'title.akas', 'title.crew', 'title.principals', 'name.basics']
SKIP_TYPES   = {'videoGame'}
AKA_REGIONS  = {'US', 'GB'}
USER_AGENT   = 'moviedb (https://github.com/acidvegas/moviedb)'
BATCH_SIZE   = 100_000

SCHEMA = '''
CREATE TABLE titles     (tconst INTEGER PRIMARY KEY, type TEXT, primary_title TEXT, original_title TEXT, start_year INTEGER, end_year INTEGER, runtime INTEGER, genres TEXT, rating REAL, votes INTEGER);
CREATE TABLE episodes   (tconst INTEGER PRIMARY KEY, parent INTEGER, season INTEGER, episode INTEGER);
CREATE TABLE akas       (tconst INTEGER, title TEXT, region TEXT, language TEXT, types TEXT, attributes TEXT);
CREATE TABLE crew       (tconst INTEGER, nconst INTEGER, role TEXT);
CREATE TABLE principals (tconst INTEGER, ordering INTEGER, nconst INTEGER, category TEXT, job TEXT, characters TEXT);
CREATE TABLE names      (nconst INTEGER PRIMARY KEY, name TEXT, birth_year INTEGER, death_year INTEGER, professions TEXT, known_for TEXT, credits INTEGER, score INTEGER);
CREATE TABLE meta       (key TEXT PRIMARY KEY, value TEXT);
'''

INDEXES = '''
CREATE INDEX idx_titles_votes      ON titles (votes DESC);
CREATE INDEX idx_titles_type_votes ON titles (type, votes DESC);
CREATE INDEX idx_titles_rating     ON titles (rating DESC);
CREATE INDEX idx_titles_year       ON titles (start_year);
CREATE INDEX idx_episodes_parent   ON episodes (parent, season, episode);
CREATE INDEX idx_akas_tconst       ON akas (tconst);
CREATE INDEX idx_crew_tconst       ON crew (tconst);
CREATE INDEX idx_crew_nconst       ON crew (nconst);
CREATE INDEX idx_principals_tconst ON principals (tconst, ordering);
CREATE INDEX idx_principals_nconst ON principals (nconst);
CREATE INDEX idx_names_score       ON names (score DESC);
'''

POPULAR_FTS = '''
CREATE VIRTUAL TABLE titles_pop_fts   USING fts5(title, content='', prefix='2 3', tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE episodes_pop_fts USING fts5(title, content='', prefix='2 3', tokenize='unicode61 remove_diacritics 2');
INSERT INTO titles_pop_fts (rowid, title)
	SELECT t.tconst, t.primary_title || CASE WHEN t.original_title != t.primary_title THEN ' ' || t.original_title ELSE '' END || coalesce(' ' || (SELECT group_concat(DISTINCT a.title) FROM akas a WHERE a.tconst = t.tconst AND a.title != t.primary_title), '')
	FROM titles t WHERE t.type != 'tvEpisode' AND t.votes >= 500;
INSERT INTO episodes_pop_fts (rowid, title) SELECT tconst, primary_title FROM titles WHERE type = 'tvEpisode' AND votes >= 500;
'''


def download(status: dict) -> dict:
	'''
	Download any dataset whose remote Last-Modified differs from the local copy.

	:param status: Status dict to update with progress
	'''

	meta_path = DATA_DIR / 'datasets.json'
	meta      = json.loads(meta_path.read_text()) if meta_path.exists() else {}

	for name in DATASETS:
		url  = f'{DATASET_URL}/{name}.tsv.gz'
		path = DATA_DIR / f'{name}.tsv.gz'

		with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Range': 'bytes=0-0'}), timeout=15) as response:
			modified = response.headers.get('Last-Modified')

		if path.exists() and meta.get(name) == modified:
			continue

		set_status(status, step=f'Downloading {name}', rows=0)
		tmp = path.with_suffix('.gz.part')

		with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': USER_AGENT}), timeout=15) as response, open(tmp, 'wb') as fp:
			total = int(response.headers.get('Content-Length', 0))
			done  = 0
			while chunk := response.read(1 << 20):
				fp.write(chunk)
				done += len(chunk)
				if done % (50 << 20) < (1 << 20):
					set_status(status, progress=f'{done >> 20:,} / {total >> 20:,} MB')

		tmp.replace(path)
		meta[name] = modified
		meta_path.write_text(json.dumps(meta, indent=2))

	return meta


def build(status: dict, meta: dict):
	'''
	Build a fresh SQLite database from the downloaded datasets and swap it in atomically.

	:param status: Status dict to update with progress
	:param meta: Dataset Last-Modified values
	'''

	tmp_path = DB_PATH.with_suffix('.db.building')
	tmp_path.unlink(missing_ok=True)

	db = sqlite3.connect(tmp_path)
	db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-1000000; PRAGMA temp_store=FILE;')
	db.executescript(SCHEMA)

	set_status(status, step='Loading ratings')
	ratings = {tid(row[0]): (float(row[1]), int(row[2])) for row in read_tsv('title.ratings', status)}

	set_status(status, step='Loading titles')
	kept = set()

	def titles():
		for row in read_tsv('title.basics', status):
			if row[4] == '1' or row[1] in SKIP_TYPES:
				continue
			tconst = tid(row[0])
			kept.add(tconst)
			rating, votes = ratings.get(tconst, (None, 0))
			yield tconst, row[1], row[2], row[3], num(row[5]), num(row[6]), num(row[7]), null(row[8]), rating, votes

	insert(db, 'titles', 10, titles())

	set_status(status, step='Loading episodes')
	insert(db, 'episodes', 4, ((tid(r[0]), tid(r[1]), num(r[2]), num(r[3])) for r in read_tsv('title.episode', status) if tid(r[0]) in kept))

	set_status(status, step='Loading alternate titles (US/GB/English)')
	insert(db, 'akas', 6, ((tid(r[0]), r[2], null(r[3]), null(r[4]), null(r[5]), null(r[6])) for r in read_tsv('title.akas', status) if (r[3] in AKA_REGIONS or r[4] == 'en') and tid(r[0]) in kept))

	people = {}

	def credit(nconst: int, tconst: int):
		entry = people.setdefault(nconst, [0, 0])
		entry[0] += 1
		entry[1] += ratings.get(tconst, (0, 0))[1]

	set_status(status, step='Loading directors & writers')

	def crew():
		for row in read_tsv('title.crew', status):
			tconst = tid(row[0])
			if tconst not in kept:
				continue
			for index, role in ((1, 'director'), (2, 'writer')):
				if row[index] != '\\N':
					for nconst in dict.fromkeys(row[index].split(',')):
						credit(tid(nconst), tconst)
						yield tconst, tid(nconst), role

	insert(db, 'crew', 3, crew())

	set_status(status, step='Loading cast & crew (principals)')

	def principals():
		for row in read_tsv('title.principals', status):
			tconst = tid(row[0])
			if tconst not in kept:
				continue
			nconst = tid(row[2])
			if row[3] not in ('director', 'writer'):
				credit(nconst, tconst)
			yield tconst, int(row[1]), nconst, row[3], null(row[4]), null(row[5])

	insert(db, 'principals', 6, principals())

	set_status(status, step='Loading people')
	insert(db, 'names', 8, ((tid(r[0]), r[1], num(r[2]), num(r[3]), null(r[4]), null(r[5]), *people[tid(r[0])]) for r in read_tsv('name.basics', status) if tid(r[0]) in people and r[1] != '\\N'))
	del ratings, kept, people

	set_status(status, step='Building indexes', rows=0, progress='')
	for statement in filter(str.strip, INDEXES.split(';')):
		set_status(status, progress=statement.split()[2])
		db.execute(statement)

	set_status(status, step='Building search index', progress='titles')
	db.executescript('''
		CREATE VIRTUAL TABLE titles_fts   USING fts5(title, content='', prefix='2 3', tokenize='unicode61 remove_diacritics 2');
		CREATE VIRTUAL TABLE episodes_fts USING fts5(title, content='', prefix='2 3', tokenize='unicode61 remove_diacritics 2');
		CREATE VIRTUAL TABLE names_fts    USING fts5(name,  content='', prefix='2 3', tokenize='unicode61 remove_diacritics 2');
		INSERT INTO titles_fts (rowid, title)
			SELECT t.tconst, t.primary_title || CASE WHEN t.original_title != t.primary_title THEN ' ' || t.original_title ELSE '' END || coalesce(' ' || (SELECT group_concat(DISTINCT a.title) FROM akas a WHERE a.tconst = t.tconst AND a.title != t.primary_title), '')
			FROM titles t WHERE t.type != 'tvEpisode';
	''')
	set_status(status, progress='episodes')
	db.execute("INSERT INTO episodes_fts (rowid, title) SELECT tconst, primary_title FROM titles WHERE type = 'tvEpisode'")
	set_status(status, progress='people')
	db.execute('INSERT INTO names_fts (rowid, name) SELECT nconst, name FROM names')

	set_status(status, progress='popular')
	db.executescript(POPULAR_FTS)

	set_status(status, step='Optimizing', progress='')
	for table in ('titles_fts', 'episodes_fts', 'names_fts', 'titles_pop_fts', 'episodes_pop_fts'):
		db.execute(f"INSERT INTO {table} ({table}) VALUES ('optimize')")
	db.executemany('INSERT INTO meta VALUES (?, ?)', [('built', time.strftime('%Y-%m-%d %H:%M:%S')), ('datasets', json.dumps(meta))])
	db.commit()
	db.execute('ANALYZE')
	db.close()

	tmp_path.replace(DB_PATH)


def insert(db: sqlite3.Connection, table: str, width: int, rows):
	'''
	Bulk insert rows into a table in batches.

	:param db: Database connection
	:param table: Table name
	:param width: Number of columns
	:param rows: Iterable of row tuples
	'''

	sql   = f'INSERT INTO {table} VALUES ({",".join("?" * width)})'
	batch = []

	for row in rows:
		batch.append(row)
		if len(batch) >= BATCH_SIZE:
			db.executemany(sql, batch)
			batch.clear()

	db.executemany(sql, batch)
	db.commit()


def null(value: str) -> str | None:
	'''
	Convert an IMDb null marker to None.

	:param value: Raw field value
	'''

	return None if value == '\\N' else value


def num(value: str) -> int | None:
	'''
	Convert a numeric field to int, or None for nulls.

	:param value: Raw field value
	'''

	return None if value == '\\N' else int(value)


def read_tsv(name: str, status: dict):
	'''
	Yield split rows from a gzipped dataset, skipping the header.

	:param name: Dataset name
	:param status: Status dict to update with row progress
	'''

	with gzip.open(DATA_DIR / f'{name}.tsv.gz', 'rt', encoding='utf-8') as fp:
		next(fp)
		for count, line in enumerate(fp, 1):
			if count % 1_000_000 == 0:
				set_status(status, rows=count)
			yield line.rstrip('\n').split('\t')


def set_status(status: dict, **fields):
	'''
	Update the status dict and write it atomically to disk.

	:param status: Status dict
	'''

	status.update(fields)
	tmp = STATUS_PATH.with_suffix('.tmp')
	tmp.write_text(json.dumps(status))
	tmp.replace(STATUS_PATH)


def tid(value: str) -> int:
	'''
	Convert an IMDb identifier (tt0000001 / nm0000001) to an integer.

	:param value: IMDb identifier
	'''

	return int(value[2:])


def main():
	'''Download updated datasets and rebuild the database.'''

	DATA_DIR.mkdir(exist_ok=True)
	os.environ['SQLITE_TMPDIR'] = str(DATA_DIR)

	status = {'state': 'running', 'step': 'Checking for updates', 'rows': 0, 'progress': '', 'started': time.time(), 'finished': None, 'error': None}
	set_status(status)

	try:
		build(status, download(status))
		set_status(status, state='done', step='Complete', rows=0, progress='', finished=time.time())
	except Exception as e:
		set_status(status, state='error', error=f'{type(e).__name__}: {e}', finished=time.time())
		raise



if __name__ == '__main__':
	main()
