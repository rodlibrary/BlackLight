# Solr configset

`solr/conf` is the configset for the `preservica` core. It is used by
`docker-compose.yml` and, through `.solr_wrapper.yml`, by `solr_wrapper` in the
generated Rails app.

It starts from the Solr configuration bundled with Blacklight 9.3
(`lib/generators/blacklight/templates/solr/conf`, Apache License 2.0), so all
of Blacklight's dynamic-field suffixes work. Changes from that copy:

- `/select` default `qf`/`pf` name this project's fields (`title_tesim`,
  `creator_tesim`, ...) instead of the demo's MARC fields.
- Autocomplete (`suggest`) is built only from titles, creators, subjects, places
  and collections, so ids, URLs and file names never appear as suggestions.
- Spellcheck dictionaries use `title_tesim`, `creator_tesim` and `subject_*`.
- The Hydra `permissions` handler and unused files (XSLT, elevate, synonyms and
  similar) were removed.

The field profile written by the ingest is in `docs/solr-fields.md`.

## Production

- Run Solr on a private network; only the Rails app should reach it.
- Create the core from this configset (`solr create -c preservica -d solr/conf`
  or upload it to ZooKeeper for SolrCloud) with the `analysis-extras` module
  enabled.
- After schema changes, reload the core and re-run a full ingest.
