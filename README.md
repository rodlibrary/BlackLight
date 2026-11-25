# PreservicaBlackLight

A public search and browse site for the collections in Preservica, built with:

- **Python ingest** (`ingest/`): harvests Preservica and writes public records to Solr
  - OAI-PMH for descriptive metadata (MODS where embedded, Dublin Core for everything else)
  - the Entity API for the folder hierarchy: breadcrumbs, collection pages, "search within"
  - the Content API for thumbnails, cached as static files
- **Apache Solr** (`solr/conf`): the index, with a configset based on Blacklight's
- **Blacklight 9 on Rails** (`blacklight/`): the discovery interface

It grew out of the Preservica adapter in
[UnifiedSearch](https://github.com/rodlibrary/UnifiedSearch) and keeps its
safety rules (public records only, guarded deletes, no secrets in files,
sanitized HTML).

## What the site offers

- Keyword, title, creator, subject and full-text search with facets for kind
  (item or collection), collection, type, creator, subject, place, genre, year and language
- Home page listing the top-level collections; an **About** page (/about), linked from the header
- On every record, breadcrumbs through the Preservica folders it sits in
- On a collection (folder) page: its subcollections, "Browse all N items",
  and a search box limited to that collection
- Thumbnails in results. Item and collection pages hand visitors off to
  Preservica Universal Access with an "Open in Preservica" button (the
  library's chosen access model), or show an image, audio, video, PDF or IIIF
  preview instead if access copies or manifests are published elsewhere (IIIF is
  optional and off by default; see below)
- **Map** (/map), linked beside the search results: records with coordinates as
  pins, with "Search this area"; a "Location: On the map" facet; a small map on
  each record page with a location; and, once IIIF is turned on, georeferenced
  scanned maps overlaid on a modern basemap with Allmaps (transparency slider,
  link to the Allmaps Viewer)
- Advanced search (/advanced), linked beside the search bar: one box per search field, plus checkbox limits. Citations and autocomplete from Blacklight. There are no logins, bookmarks or search history: the site has no user accounts.

## Repository layout

```
ingest/                     Python ingest package (python -m ingest)
  core.py                   the Record and its Solr fields
  cli.py                    check / run commands, checkpoints, sweep
  solr.py                   batched writes and stale-record sweep
  preservica/
    client.py               token login, OAI-PMH, Entity API, Content API
    oai.py                  ListRecords paging, Identify, ListMetadataFormats
    metadata.py             MODS and Dublin Core mapping
    hierarchy.py            folder tree from the Entity API
    thumbnails.py           thumbnail cache
    harvest.py              public checks and Record building
config.example.yaml         settings (copy to config.yaml)
solr/conf/                  Solr configset for the 'preservica' core
docker-compose.yml          Solr for development
blacklight/                 files copied into the generated Rails app
  template.rb               Rails template (pins Blacklight 9)
  app/controllers/catalog_controller.rb
  app/components/           breadcrumbs, collection contents, media preview
  app/helpers/application_helper.rb
  app/views/                home page, About page and its header link
  config/locales/           site name and wording
bin/setup_blacklight_app    generates the app and copies the overlay
samples/demo-docs.json      seven invented records for trying the interface
docs/solr-fields.md         field profile
docs/accessibility.md       WCAG 2.1 AA checks, fixes and what still needs testing
tests/                      pytest suite (no network or Solr needed)
iiif/                       serverless IIIF pipeline on AWS (see iiif/README.md)
```

## Requirements

- Python 3.10 or later
- Ruby 3.2 or later and Rails 8 (Blacklight 9 supports Rails 7.2 and 8)
- Docker (for Solr), or Java 17+ to run Solr with `solr_wrapper`
- Node.js 20 and Yarn, Git

## Quick start

### 1. Solr

```shell
docker compose up -d solr          # http://localhost:8983/solr/#/preservica
```

### 2. Blacklight

```shell
bin/setup_blacklight_app           # creates ./preservica_app and copies blacklight/ into it
cd preservica_app && bin/rails server   # http://localhost:3000
```

Rerun `bin/setup_blacklight_app` after changing anything in `blacklight/`.
Without Docker, run `bundle exec solr_wrapper` inside `preservica_app`
instead; the script points it at `solr/conf`.

To look at the interface before connecting Preservica, load the demo records,
and remove them before the first real harvest:

```shell
curl 'http://localhost:8983/solr/preservica/update?commit=true' \
  -H 'Content-Type: application/json' --data-binary @samples/demo-docs.json
# later:
curl 'http://localhost:8983/solr/preservica/update?commit=true' \
  -H 'Content-Type: text/xml' --data-binary '<delete><query>ingest_run_ssi:demo</query></delete>'
```

### 3. Ingest

```shell
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml

# A read-only service account whose role sees only the security tags you publish.
export PRESERVICA_BASE_URL=https://<server>.preservica.com
export PRESERVICA_OAI_URL=<your OAI-PMH endpoint>
export PRESERVICA_USERNAME=...
export PRESERVICA_PASSWORD=...
export PRESERVICA_TENANT=...        # if your login needs it

python -m ingest check                                # login, Identify, formats on a sample asset
python -m ingest run --dry-run -v --backup-dir data   # harvest and map; review data/*.json
python -m ingest run                                  # full harvest
python -m ingest run --incremental                    # only changes since the last successful run
```

A sensible schedule: `--incremental` nightly (or hourly) and a full run weekly.

| Option | Effect |
| --- | --- |
| `--incremental` | harvest only changes since the last successful run (`state_dir` holds the checkpoint) |
| `--dry-run` | harvest and map; don't write to Solr, download thumbnails or move the checkpoint |
| `--backup-dir DIR` | also save the Solr documents as JSON |
| `--no-sweep` | don't remove records missing from a full harvest |
| `--allow-large-delete` | let the sweep remove more than `max_delete_fraction` of the index |
| `--refresh-thumbnails` | download every thumbnail again |

### 4. Tests

```shell
pip install -r requirements-dev.txt
python -m pytest
```

## Configuration highlights

All settings are in `config.example.yaml`, with comments. The ones to decide first:

- **`metadata_prefix`**: `[MODS, oai_dc]` indexes MODS where an asset has it and
  Dublin Core otherwise. Use `python -m ingest check` to see what your assets carry.
- **`public_security_tags`**: the tags you publish (default `open`).
- **`resolve_hierarchy`**: costs one Entity API request per asset, plus one per
  folder, on each run that sees the asset. Turn it off for a quick first look.
- **`skip_top_levels`**: hide administrative folders at the top of the tree,
  so the first level users see is your real collections.
- **`thumbnails`**: download thumbnails into `thumbnail_dir`, which the Rails
  app serves at `/thumbnails` (set `THUMBNAIL_BASE_URL` if a CDN serves them).
- **Link templates**: set `landing_url_template` (and `folder_landing_url_template`)
  to your Universal Access URL pattern so item pages hand visitors off to
  Preservica. If you also publish access
  copies, set `media_url_template` so record pages preview them. IIIF manifests
  are a separate, optional step: see "IIIF images and manifests (optional)" below.

## How the ingest stays safe

- **Public records only.** A record is removed from the index (not added) if the
  service account can't see it, if its security tag (in the OAI record or from
  the Entity API) isn't in `public_security_tags`, or if its MODS
  `accessCondition type="restriction on access"` says restricted, closed or
  embargoed. `to_solr()` refuses anything not marked public, and only
  `http(s)` URLs are stored.
- **Hidden folders stay hidden.** A folder that isn't public, and everything
  above it, is left out of breadcrumbs and never becomes a collection record.
  If a folder is closed later, its own record goes at the next run that sees
  the change; the breadcrumbs of the items inside it are rebuilt by the next
  full run, so schedule one regularly.
- **Deleted and withdrawn items disappear.** Incremental runs apply the
  deletions Preservica reports. A full run also removes records it didn't see,
  but stops rather than delete more than 20% of the index (configurable), and a
  failed harvest never sweeps or moves the checkpoint. Thumbnails of removed
  records are deleted too.
- **Secrets stay out of files.** `config.yaml` refers to `${ENV_VARS}` and is in `.gitignore`.
- **Harvested HTML is sanitized.** Descriptions and notes render through an
  allowlist; nothing from Preservica is marked `html_safe`.

## Maps

- **Coordinates** come from MODS `subject/cartographics/coordinates`, Dublin Core
  `coverage` values that are points, or a DCDS_local element mapped to
  `coordinates` in `local_metadata`. Accepted forms: `42.51, -92.46`,
  `42.51N 92.46W`, `POINT(-92.46 42.51)`, and decimal bounding boxes (centre point).
- **Georeferenced maps** need IIIF, so they arrive with it: with `iiif_enabled: true`,
  set `georeference_url_template` (the item's IIIF Georeference Annotation, for
  example from Allmaps). Record pages then overlay the scanned map. Points on the
  Map page don't need IIIF.
- **Outside services** the browser loads: Leaflet and the Allmaps plugin from
  cdn.jsdelivr.net, and map tiles from tile.openstreetmap.org. OpenStreetMap's
  tile servers are for light use; for production set `MAP_TILE_URL` (and
  `MAP_TILE_ATTRIBUTION`) to a tile provider the university uses. Allow these
  hosts if the site sets a Content Security Policy.

## Adding a source system

Each record's `source_ssi` field names the system it came from (`source` in `config.yaml`,
`preservica` today), and each source's full harvest only removes its own records. The About
page's Technology section lists a system automatically once its records are in the index:
`IndexedSources` reads the `source_ssi` facet (cached for an hour) and shows the wording under
`preservica.about.systems` in `config/locales/preservica.en.yml`. MuseumPlus (`museumplus`),
UNI ScholarWorks (`scholarworks`), Janeway (`janeway`) and Archive-It (`archiveit`) already have
wording there. A new source needs a key there with the same name as its `source` value, or it
is left off the page. Set `DC_SOURCES=preservica,museumplus` to override the list, for example
on staging.

## IIIF images and manifests (optional)

IIIF is **off by default**. Until it's turned on, every item keeps the "Open in Preservica"
hand-off and nothing depends on AWS. Turn it on once the AWS pipeline is running:

1. Deploy [`iiif/`](iiif/README.md).
2. In `config.yaml`, set `iiif_enabled: true` and fill in the manifest URLs, then run a full
   harvest.
3. For the Blacklight app, set `IIIF_ENABLED=true` (this shows IIIF on the About page) and
   `IIIF_VIEWER_URL` (e.g. `https://uv-v4.netlify.app/#?manifest=`) to embed a viewer.

Turning it off again is the reverse: `iiif_enabled: false` and a full harvest.

Preservica Enterprise doesn't publish IIIF, so [`iiif/`](iiif/README.md) adds it on AWS.
Preservica webhooks and a nightly check queue public image assets. A converter
(pyPreservica and libvips) makes tiled TIFFs for serverless-iiif and writes IIIF
Presentation 3 manifests, and CloudFront serves both. Set `iiif_manifest_url_template`
and `iiif_manifest_index_url` from its outputs. Items in the index then get a viewer (and
the map overlay); everything else keeps the Open in Preservica hand-off.

## Deployment notes

- Keep Solr on a private network; only the Rails app should reach it.
- Serve `public/thumbnails` (or a CDN copy) as static files.
- Run the ingest from cron or a scheduler with the environment variables set,
  on the same host as the thumbnail folder.
