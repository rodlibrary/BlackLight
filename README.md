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
  preview instead if access copies or manifests are published elsewhere
- Citations and autocomplete from Blacklight. There are no logins, bookmarks or search history: the site has no user accounts.

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
tests/                      pytest suite (no network or Solr needed)
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
  copies or IIIF manifests, set the `*_url_template` settings so record pages
  link and preview them. Set `IIIF_VIEWER_URL` (e.g.
  `https://uv-v4.netlify.app/#?manifest=`) in the Rails environment to embed a viewer.

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

## Deployment notes

- Keep Solr on a private network; only the Rails app should reach it.
- Serve `public/thumbnails` (or a CDN copy) as static files.
- Run the ingest from cron or a scheduler with the environment variables set,
  on the same host as the thumbnail folder.
