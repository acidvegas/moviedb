# MovieDB

## Live demo: [movies.supernets.org](https://movies.supernets.org)

A self-hosted movie and TV browser built on the full IMDb datasets. Everything lives on your own server, so it keeps working at home even when the internet is down.

## Features

- Browse and search all 12M+ IMDb titles and the people credited on them, no account needed
- Accounts with their own ratings, lists, watchlist, Letterboxd sync and streaming services *(username and password only, no email, captcha on sign up)*
- Admin page to approve, delete or reset the password of any account, and to close registration or require approval
- Title pages with plot, trailer, full cast and crew, streaming availability and more from TMDB
- Rate titles and people *(half-star steps)*, mark titles watched or add them to your watchlist
- Custom lists with CSV/JSON export
- Recommendations based on your ratings, watched titles, watchlist, a list or a single title
- Follow directors and actors to see their upcoming and recent releases
- Letterboxd sync *(daily watchlist sync plus full import from a Letterboxd export zip)*
- Filter by the streaming services you subscribe to
- English subtitles for movies and episodes from SubDL and OpenSubtitles, saved on the server, with a daily prefetch for every library *(users can add their own API keys to a shared pool)*
- Links to 28 third-party streaming sites on every title page *(direct links where the site uses TMDB/IMDb ids, otherwise a search)*
- Top torrents by seeders from a [bitmagnet](https://bitmagnet.io/) instance, with magnet copy and a link to search for more *(optional; users can set their own bitmagnet URL or fall back to the admin's shared one, without the search link)*
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

Set `ADMIN_PASSWORD` in `.env`, restart the service, then open `http://<server-ip>:5000`, log in as `admin`, add your TMDB key under **Admin**, then your Letterboxd username and streaming services under **Settings**.

## Docker

```sh
cp .env.example .env
docker compose up -d --build
```

The repo folder is mounted into the container, so `imdb.db`, `user.db` and `data/` stay in it across rebuilds. The app listens on `127.0.0.1:20000` for a reverse proxy in front.

## Running manually

```sh
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python app.py
```

To build or update the database by hand, run `venv/bin/python importer.py`.

## Styling

The page styles are pre-built into `static/tailwind.css` with the [Tailwind CSS standalone CLI](https://github.com/tailwindlabs/tailwindcss/releases/tag/v3.4.16) *(v3.4.16, no Node needed)*. After adding or changing classes in the templates, rebuild it:

```sh
./tailwindcss -c tailwind.config.js -i static/tailwind.in.css -o static/tailwind.css --minify
```

## Configuration

Set in `.env` *(see `.env.example`)*:

| Variable         | Default   | Description                                                |
|------------------|-----------|------------------------------------------------------------|
| `HOST`           | `0.0.0.0` | Address to bind to                                         |
| `PORT`           | `5000`    | Port to listen on                                          |
| `ADMIN_PASSWORD` |           | Password of the `admin` account *(applied on every start)* |

Everything else is set in the web interface: per-account options under **Settings**, site settings and accounts under **Admin** *(admin only)*.

## Files

| Path                 | Description                                                       |
|----------------------|-------------------------------------------------------------------|
| `app.py`             | Web app *(Quart)*, background scheduler, TMDB and Letterboxd      |
| `importer.py`        | Downloads the IMDb datasets and builds `imdb.db`                  |
| `setup.sh`           | Installer and systemd service setup                               |
| `Dockerfile`         | Container image *(used by `docker-compose.yml`)*                  |
| `tailwind.config.js` | Tailwind settings used to build `static/tailwind.css`             |
| `imdb.db`            | IMDb database, rebuilt weekly                                     |
| `user.db`            | Accounts, ratings, lists, watched/watchlist, settings and caches  |
| `data/`              | Downloaded datasets, importer status, cached images and subtitles |
| `templates/`         | Page templates                                                    |
| `static/`            | CSS, JS, icons and bundled front-end libraries                    |

Back up `user.db`. Everything else can be rebuilt.

## Data sources

- [IMDb non-commercial datasets](https://developer.imdb.com/non-commercial-datasets/) *(personal, non-commercial use only)*
- [TMDB](https://www.themoviedb.org/) for plots, images, credits, trailers and streaming availability *(streaming data provided by JustWatch)*
- [Letterboxd](https://letterboxd.com/) for watchlist and watched sync, and as a poster fallback
- [SubDL](https://subdl.com/) and [OpenSubtitles](https://www.opensubtitles.com/) for subtitles
- [bitmagnet](https://bitmagnet.io/) *(self-hosted)* for torrents

---

###### Mirrors: [SuperNETs](https://git.supernets.org/acidvegas/) • [GitHub](https://github.com/acidvegas/) • [GitLab](https://gitlab.com/acidvegas/) • [Codeberg](https://codeberg.org/acidvegas/)
