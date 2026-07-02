# Max WheyTV

Universal Stremio addon — Movies, Series & Live TV from every corner of the world.

## Features

- 🎬 **Movies & Series** — MovieBox backend, 1000+ titles, multi-language
- 📺 **Live TV** — 8,000+ IPTV channels from 12+ countries
- ⚽ **FIFA & Football** — World Cup, FIFA+, La Liga, Real Madrid TV
- 🌍 **Multi-language** — 15+ languages (English, Hindi, Spanish, French, etc.)
- 📱 **Platform-aware** — Fast mode for TV/Mobile (~2s), full mode for Desktop
- ⭐ **RPDB ratings** — Rating posters on all content
- 📊 **TMDB metadata** — Movie info, posters, descriptions
- 📺 **TVDB metadata** — Series info with full episode lists

## Configure

Open `/configure/` in your browser to select:
- Enable/disable Movies & Series
- Enable/disable IPTV
- Language preferences (multi-select)
- IPTV countries (multi-select)
- IPTV categories (multi-select)
- Resolution (4K/1080p/720p)
- Platform (TV/Mobile/Desktop)

## Install

Add this URL to Stremio:

```
https://max-wheytv.up.railway.app/manifest.json
```

Or use the configure page to customize your install.

## Tech Stack

- Python / FastAPI
- MovieBox API (h5-api.aoneroom.com)
- TMDB API for movie metadata
- TVDB API for series metadata
- RPDB for rating posters
- IPTV sources: iptv-org, masqueradarr, Quincunx33, Kufa TV
