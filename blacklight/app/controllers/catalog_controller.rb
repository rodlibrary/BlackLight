# frozen_string_literal: true

# Blacklight configuration for the Preservica discovery site.
#
# Field names follow the documents written by the ingest pipeline
# (ingest/core.py, docs/solr-fields.md). Keep the two in step.
class CatalogController < ApplicationController
  include Blacklight::Catalog

  # Weighted fields for the "All fields" search. Set explicitly so Blacklight
  # doesn't depend on the Solr handler defaults.
  ALL_FIELDS_QF = %w[
    title_tesim^20 alternative_title_tesim^10 creator_tesim^8 contributor_tesim^4 subject_tesim^5
    collection_ssim^3 place_ssim^3 abstract_tesim^2 note_tesim full_text_teim identifier_ssim id
  ].join(' ').freeze
  ALL_FIELDS_PF = 'title_tesim^30 abstract_tesim^5 full_text_teim^2'

  configure_blacklight do |config|
    config.default_solr_params = {
      rows: 10,
      defType: 'edismax',
      qf: ALL_FIELDS_QF,
      pf: ALL_FIELDS_PF
    }

    config.index.title_field = 'title_tesim'
    # Cached Preservica thumbnail or a public thumbnail URL (ApplicationHelper#preservica_thumbnail).
    config.index.thumbnail_method = :preservica_thumbnail
    config.show.title_field = 'title_tesim'
    # Breadcrumbs above every record and, on collection pages, the collection's contents.
    config.show.document_component = PreservicaDocumentComponent
    # Image, PDF, audio, video or IIIF preview above the record's metadata.
    config.show.document_embed_component = MediaPreviewComponent

    # --- Search results -------------------------------------------------------
    config.add_index_field 'entity_type_ssim', label: 'Kind'
    config.add_index_field 'ancestor_titles_ssm', label: 'Part of', helper_method: :render_part_of
    config.add_index_field 'creator_ssim', label: 'Creator', link_to_facet: true
    config.add_index_field 'date_display_ssm', label: 'Date'
    config.add_index_field 'resource_type_ssim', label: 'Type'
    config.add_index_field 'abstract_tesim', label: 'Summary', helper_method: :render_summary

    # --- Record page ----------------------------------------------------------
    config.add_show_field 'alternative_title_tesim', label: 'Other title'
    config.add_show_field 'creator_ssim', label: 'Creator', link_to_facet: true
    config.add_show_field 'contributor_ssim', label: 'Contributor', link_to_facet: true
    config.add_show_field 'publisher_ssim', label: 'Publisher', link_to_facet: true
    config.add_show_field 'date_display_ssm', label: 'Date'
    config.add_show_field 'resource_type_ssim', label: 'Type', link_to_facet: true
    config.add_show_field 'genre_ssim', label: 'Genre', link_to_facet: true
    config.add_show_field 'abstract_tesim', label: 'Description', helper_method: :render_rich_text
    config.add_show_field 'note_tesim', label: 'Notes', helper_method: :render_rich_text
    config.add_show_field 'subject_ssim', label: 'Subjects', link_to_facet: true
    config.add_show_field 'place_ssim', label: 'Places', link_to_facet: true
    config.add_show_field 'language_ssim', label: 'Language', link_to_facet: true
    config.add_show_field 'extent_ssm', label: 'Extent of original'
    config.add_show_field 'collection_ssim', label: 'Collection', link_to_facet: true
    config.add_show_field 'relation_ssm', label: 'Related'
    config.add_show_field 'physical_location_ssm', label: 'Original held at'
    config.add_show_field 'shelf_locator_ssm', label: 'Location of original'
    config.add_show_field 'rights_note_ssm', label: 'Rights'
    config.add_show_field 'rights_uri_ssi', label: 'Rights statement', helper_method: :render_safe_link
    config.add_show_field 'file_format_ssim', label: 'File format'
    config.add_show_field 'doi_ssi', label: 'DOI', helper_method: :render_doi_link
    config.add_show_field 'identifier_ssim', label: 'Identifier'
    config.add_show_field 'url_ssi', label: 'View in Preservica', helper_method: :render_safe_link

    # --- Facets ---------------------------------------------------------------
    config.add_facet_field 'entity_type_ssim', label: 'Show', limit: 5
    config.add_facet_field 'collection_ssim', label: 'Collection', limit: 10
    config.add_facet_field 'resource_type_ssim', label: 'Type', limit: 10
    config.add_facet_field 'creator_ssim', label: 'Creator', limit: 10
    config.add_facet_field 'subject_ssim', label: 'Subject', limit: 10, index_range: 'A'..'Z'
    config.add_facet_field 'place_ssim', label: 'Place', limit: 10
    config.add_facet_field 'genre_ssim', label: 'Genre', limit: 10
    # Plain year facet; blacklight_range_limit can replace it with a slider on the same field.
    config.add_facet_field 'year_isim', label: 'Year', limit: 15, sort: 'index'
    config.add_facet_field 'language_ssim', label: 'Language', limit: 10
    # Not shown in the sidebar: used by breadcrumb, "browse this collection" and
    # "search within" links. The helper turns folder ids into titles in the
    # "You searched for" constraints.
    config.add_facet_field 'ancestor_ids_ssim', label: 'Within', show: false, helper_method: :folder_title
    config.add_facet_field 'parent_id_ssi', label: 'Directly in', show: false, helper_method: :folder_title
    config.add_facet_field 'level', label: 'Collections', show: false, query: {
      top: { label: 'Top-level collections', fq: 'entity_type_ssi:folder AND depth_isi:0' }
    }
    config.add_facet_fields_to_solr_request!

    # --- Search fields --------------------------------------------------------
    config.add_search_field 'all_fields', label: 'All fields'

    config.add_search_field('title') do |field|
      field.label = 'Title'
      field.solr_parameters = { qf: 'title_tesim^5 alternative_title_tesim', pf: 'title_tesim' }
    end

    config.add_search_field('creator') do |field|
      field.label = 'Creator'
      field.solr_parameters = { qf: 'creator_tesim contributor_tesim', pf: 'creator_tesim' }
    end

    config.add_search_field('subject') do |field|
      field.label = 'Subject'
      field.solr_parameters = { qf: 'subject_tesim place_ssim', pf: 'subject_tesim' }
    end

    config.add_search_field('full_text') do |field|
      field.label = 'Full text and transcripts'
      field.solr_parameters = { qf: 'full_text_teim', pf: 'full_text_teim' }
    end

    # --- Sorting --------------------------------------------------------------
    config.add_sort_field 'relevance', sort: 'score desc, date_sort_dtsi desc', label: 'Relevance'
    config.add_sort_field 'title', sort: 'title_ssort asc', label: 'Title A-Z'
    config.add_sort_field 'date_asc', sort: 'date_sort_dtsi asc, title_ssort asc', label: 'Oldest first'
    config.add_sort_field 'date_desc', sort: 'date_sort_dtsi desc, title_ssort asc', label: 'Newest first'
    config.add_sort_field 'creator', sort: 'creator_ssort asc, title_ssort asc', label: 'Creator A-Z'

    # --- Tools ----------------------------------------------------------------
    config.add_results_document_tool(:bookmark, component: Blacklight::Document::BookmarkComponent, if: :render_bookmarks_control?)
    config.add_results_collection_tool(:sort_widget)
    config.add_results_collection_tool(:per_page_widget)
    config.add_results_collection_tool(:view_type_group)

    config.add_show_tools_partial(:bookmark, component: Blacklight::Document::BookmarkComponent, if: :render_bookmarks_control?)
    config.add_show_tools_partial(:citation)
    # Email and SMS need a configured mailer/SMS gateway; enable them once one exists:
    # config.add_show_tools_partial(:email, callback: :email_action, validator: :email_params_valid?)

    config.add_nav_action(:collections, partial: 'shared/collections_nav')
    config.add_nav_action(:bookmark, partial: 'blacklight/nav/bookmark', if: :render_bookmarks_control?)
    config.add_nav_action(:search_history, partial: 'blacklight/nav/search_history')

    config.spell_max = 5
    config.autocomplete_enabled = true
    config.autocomplete_path = 'suggest'
  end
end
