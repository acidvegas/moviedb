# MovieDB

A self-hosted movie and TV browser built on the full IMDb datasets. Everything lives on your own server, so it keeps working at home even when the internet is down.

## Features

- Browse and search all 12M+ IMDb titles and the people credited on them
- Title pages with plot, trailer, full cast and crew, streaming availability and more from TMDB
- Rate titles and people *(half-star steps)*, mark titles watched or add them to your watchlist
- Custom lists with CSV/JSON export
- Recommendations based on your ratings, watched titles, watchlist, a list or a single title
- Follow directors and actors to see their upcoming and recent releases
- Letterboxd sync *(daily watchlist sync plus full import from a Letterboxd export zip)*
- Filter by the streaming services you subscribe to
- English subtitles for movies and episodes from SubDL and OpenSubtitles, saved on the server, with a daily prefetch for your library
- Links to 28 third-party streaming sites on every title page *(direct links where the site uses TMDB/IMDb ids, otherwise a search)*
- Top torrents by seeders from a [bitmagnet](https://bitmagnet.io/) instance, with magnet copy and a link to search for more *(optional)*
- Offline: posters, details and all assets are stored locally and pre-cached for the most popular titles
- Weekly automatic IMDb rebuilds, swapped in atomically while the site stays up
- Infinite scroll, keyboard shortcuts *(press `?`)* and a mobile-friendly layout

## Requirements

- Linux with systemd
- Python 3.12+
- About 20 GB of free disk space *(11 GB database, a temporary copy during rebuilds, plus the image cache)*
- A free [TMDB API key](https://www.themoviedb.org/settings/api) for posters, plots, credits and streaming data *(optional but recommended)*
- A free [SubDL](https://subdl.com/) and/or [OpenSubtitles](https://www.opensubtitles.com/en/consumers) API key for subtitles *(optional)*
- A [bitmagnet](https://bitmagnet.io/) instance for torrents *(optional)*

## Install

```sh
./setup.sh
```

This creates a venv, installs the dependencies, writes `.env`, and installs and starts a `moviedb` systemd service. The IMDb database builds on first start, which takes about 30 minutes.

Then open `http://<server-ip>:5000`, go to **Settings**, and add your TMDB key, Letterboxd username and streaming services.

## Running manually

```sh
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python app.py
```

To build or update the database by hand, run `venv/bin/python importer.py`.

## Configuration

Set in `.env` *(see `.env.example`)*:

| Variable | Default   | Description        |
|----------|-----------|--------------------|
| `HOST`   | `0.0.0.0` | Address to bind to |
| `PORT`   | `5000`    | Port to listen on  |

Everything else is set in the web interface under **Settings**.

## Files

| Path          | Description                                                       |
|---------------|-------------------------------------------------------------------|
| `app.py`      | Web app *(Quart)*, background scheduler, TMDB and Letterboxd      |
| `importer.py` | Downloads the IMDb datasets and builds `imdb.db`                  |
| `setup.sh`    | Installer and systemd service setup                               |
| `imdb.db`     | IMDb database, rebuilt weekly                                     |
| `user.db`     | Your ratings, lists, watched/watchlist, settings and caches       |
| `data/`       | Downloaded datasets, importer status, cached images and subtitles |
| `templates/`  | Page templates                                                    |
| `static/`     | CSS, JS, icons and bundled front-end libraries                    |

Back up `user.db`. Everything else can be rebuilt.

## Data sources

- [IMDb non-commercial datasets](https://developer.imdb.com/non-commercial-datasets/) *(personal, non-commercial use only)*
- [TMDB](https://www.themoviedb.org/) for plots, images, credits, trailers and streaming availability *(streaming data provided by JustWatch)*
- [Letterboxd](https://letterboxd.com/) for watchlist and watched sync, and as a poster fallback
- [SubDL](https://subdl.com/) and [OpenSubtitles](https://www.opensubtitles.com/) for subtitles
- [bitmagnet](https://bitmagnet.io/) *(self-hosted)* for torrents
