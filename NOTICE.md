# Third-party notices

The [Lion Studios Source-Available Licence](LICENSE) covers the code written for this repository (`rust/src/`, the Python files,
`scripts/`, `tools/`, and `static/` except `static/vendor/` and `static/fonts/`). Everything below keeps its own terms.

## Included software and fonts

- **CesiumJS 1.146.0** (`static/vendor/cesium/`), Apache License 2.0, © 2011-2026 CesiumJS Contributors.
  [cesium.com/platform/cesiumjs](https://cesium.com/platform/cesiumjs/). Its licence and the notices of the third-party code it
  bundles are in `static/vendor/cesium/LICENSE.md`. Redistributed unmodified from the npm package `cesium@1.146.0`; no Cesium ion
  services are used.
- **d3 7.9.0** (`static/vendor/d3/`), ISC, © 2010-2023 Mike Bostock. [d3js.org](https://d3js.org).
- **3d-force-graph 1.77.0** (`static/vendor/3d-force-graph/`), MIT, © 2017 Vasco Asturiano; bundles three.js (MIT, © three.js
  authors). [github.com/vasturiano/3d-force-graph](https://github.com/vasturiano/3d-force-graph).
- **Fraunces**, **IBM Plex Sans** and **IBM Plex Mono** fonts (`static/fonts/`), SIL Open Font License 1.1; licences in
  `static/fonts/LICENSES.txt`.
- **Rust crates** named in `rust/Cargo.lock` (axum, tokio, rusqlite with bundled SQLite, r2d2, serde, regex, rust-embed, ureq and
  their dependencies), each under its own licence (MIT / Apache-2.0; SQLite is public domain).
- **Python packages** installed by you for the ingest (spaCy and `en_core_web_lg`, MIT), and poppler-utils (GPL) called as programs.

## Data shown at run time (not included)

- The **records** are public court and government releases mirrored on the Internet Archive; each data folder's `SOURCE.txt`
  names the item. They are not licensed by this repository.
- The globe's imagery: **NASA GIBS** Blue Marble (NASA data, no restrictions), **EOxCloudless 2025** by EOX IT Services GmbH
  (contains modified Copernicus Sentinel data; CC BY-NC-SA 4.0, non-commercial), **AWS Terrain Tiles** (Mapzen terrarium; USGS,
  NOAA and others). Credits are shown on the globe.
- **Wikipedia** summaries for the public-figure cards (CC BY-SA 4.0), with the article linked.

## Screenshots, video and the logo

`docs/images/*.webp`, `docs/media/` and `samples/video/` show the studio over the public records, with the globe's imagery credits
where the globe appears; frames that include EOxCloudless imagery may be reused only on EOX's terms. The showcase reel and its
score are the author's work under the licence. The Lion logo in `docs/images/logo.png` belongs to Lion Studios.

## Layout

- **README and repository-template layout** shared with [Lion Satellite Studio](https://github.com/sunnychase/lion-satellite-studio),
  itself adapted from [morluto/rea](https://github.com/morluto/rea) (MIT): the structure only; the wording is this project's own.

Created by Sunny Chase (https://github.com/sunnychase) in collaboration with Claude (Anthropic).
