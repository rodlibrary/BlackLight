# Solr field profile

Every document is written by `Record.to_solr()` in `ingest/core.py`. Blacklight
reads the same names in `blacklight/app/controllers/catalog_controller.rb`.
Change both together.

Suffixes are the dynamic fields in `solr/conf/schema.xml`:
`_tesim` English text, stored, multi-valued; `_teim` English text, not stored;
`_ssim` exact string, stored, multi-valued (facets); `_ssi` exact string, single;
`_ssm` stored only; `_ssort` sort key; `_isim`/`_isi` integers; `_dtsi` date;
`_bsi` boolean.

## Identity and source

| Field | Meaning |
| --- | --- |
| `id` | `preservica-<uuid>` (the `source` setting, then the Preservica reference) |
| `source_ssi` / `source_ssim` | machine name / display label (`label` setting) |
| `preservica_ref_ssi` | the entity's Preservica reference (UUID) |
| `entity_type_ssi` | `asset` or `folder` |
| `entity_type_ssim` | facet label: `Item` or `Collection` |
| `metadata_format_ssi` | `mods`, `oai_dc` or `entity` (folder known only from the Entity API) |
| `access_status_ssi` | always `public`; `to_solr()` refuses anything else |
| `mods_xml_ss` | the record's MODS as an XML document, stored but not indexed, served as the "Download metadata (MODS XML)" file (`mods_download`; MODS records only) |
| `ingest_run_ssi`, `indexed_at_dtsi` | run that last wrote the record; used by the stale-record sweep |

## Hierarchy

Written when `resolve_hierarchy` is on. Only public folders appear.

| Field | Meaning |
| --- | --- |
| `parent_id_ssi` | id of the containing folder |
| `ancestor_ids_ssim` | ids of every containing folder, root first; `fq=ancestor_ids_ssim:<id>` finds everything inside a folder at any depth |
| `ancestor_titles_ssm` | their titles, in the same order (breadcrumbs) |
| `depth_isi` | number of public folders above the record; top-level collections are `entity_type_ssi:folder AND depth_isi:0` |
| `collection_ssim`, `collection_id_ssi` | top public folder (and/or MODS `relatedItem type="host"`, per `collection_from`) |

## Description

| Field | MODS | Dublin Core |
| --- | --- | --- |
| `title_tesim`, `title_ssort` | `titleInfo/title` + `subTitle` | first `dc:title` |
| `alternative_title_tesim` | `titleInfo[@type]` | further `dc:title` |
| `creator_tesim`, `creator_ssim`, `creator_ssort` | `name/namePart` or `displayForm` | `dc:creator` |
| `contributor_tesim`, `contributor_ssim` | | `dc:contributor` |
| `publisher_ssim` | `originInfo/publisher` | `dc:publisher` |
| `date_display_ssm`, `date_sort_dtsi`, `year_isim` | `dateCreated`, `dateIssued`, ... (with `point`) | `dc:date` (`1960-1962` and `1960/1962` are ranges) |
| `resource_type_ssim` | `typeOfResource` | `dc:type` (DCMI types) |
| `genre_ssim` | `genre` | other `dc:type` values |
| `subject_tesim`, `subject_ssim` | `subject/topic`, `subject/name`, `subject/temporal` | `dc:subject` (split on `dc_split`) |
| `place_ssim` | `subject/geographic`, `hierarchicalGeographic` | `dc:coverage` |
| `abstract_tesim` | `abstract` | first `dc:description` |
| `note_tesim` | `note` | further `dc:description` |
| `language_ssim` | `language/languageTerm` | `dc:language` |
| `extent_ssm`, `digital_origin_ssi` | `physicalDescription` | |
| `file_format_ssim` | `physicalDescription/internetMediaType` | `dc:format` |
| `rights_uri_ssi`, `rights_note_ssm` | `accessCondition[@type="use and reproduction"]` | `dc:rights` (rightsstatements.org / Creative Commons URLs become the URI) |
| `identifier_ssim`, `doi_ssi`, `aspace_ref_ssi` | `identifier` (`type="doi"`, `type="aspace"`) | `dc:identifier` |
| `physical_location_ssm`, `shelf_locator_ssm` | `location` | |
| `relation_ssm` | | `dc:relation`, `dc:source` |
| `full_text_teim` | reserved for OCR / transcripts | |

## Local metadata fragments

Fields named in `local_metadata` (config.yaml), read from metadata fragments
through the Entity API rather than OAI-PMH.

| Field | Source |
| --- | --- |
| `department_ssim` | `department` in the DCDS_local fragment (Institutional Repository items) |

## Links and media

| Field | Source |
| --- | --- |
| `url_ssi` | `landing_url_template` / `folder_landing_url_template` |
| `media_url_ssi`, `media_type_ssi` | `media_url_template`; type from MODS/DC type and format |
| `thumbnail_url_ssm` | `thumbnail_url_template`, or the access copy for images |
| `thumbnail_file_ssi` | thumbnail cached from the Content API (`thumbnails: true`) |
| `has_thumbnail_bsi` | either of the above |
| `iiif_manifest_ssi` | `iiif_manifest_url_template`; only with `iiif_enabled: true` (off by default) |
| `georeference_url_ssi` | `georeference_url_template`: IIIF Georeference Annotation for a scanned map (Allmaps); only with `iiif_enabled: true` |
| `coordinates_srpt` | map points `lat,lon` (spatial index: "Search this area") from MODS cartographics, DC coverage or DCDS_local |
| `coordinates_ssm` | the same points, stored for display |
| `has_coordinates_bsi` | record has at least one point (Location facet, Map page) |
| `captions_url_ssi` | WebVTT captions (not yet populated) |

Only absolute `http(s)` URLs are stored.
