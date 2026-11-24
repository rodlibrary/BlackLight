# frozen_string_literal: true

# The Map page (/map): the current search's records that have coordinates, as
# pins on a Leaflet map. It takes the same q and f parameters as the catalog,
# plus bbox from "Search this area" (see SearchBuilder#add_map_area).
class MapController < ApplicationController
  include Blacklight::Searchable

  MAX_POINTS = 2_000
  FIELDS = %w[id title_tesim date_display_ssm coordinates_ssm thumbnail_url_ssm thumbnail_file_ssi].join(',')

  def index
    @response = search_service.search_results do |builder|
      builder.append(:only_mapped).merge(rows: MAX_POINTS, start: 0, fl: FIELDS, facet: false, spellcheck: false)
    end
    @points = @response.documents.flat_map { |doc| points_for(doc) }
    @bbox = SearchBuilder.parse_bbox(params[:bbox])
  end

  private

  def points_for(doc)
    Array(doc['coordinates_ssm']).filter_map do |pair|
      lat, lon = pair.to_s.split(',').map { |v| Float(v, exception: false) }
      next unless lat && lon

      {
        lat: lat, lon: lon,
        title: Array(doc['title_tesim']).first.to_s,
        date: Array(doc['date_display_ssm']).first.to_s,
        url: helpers.solr_document_path(doc.id),
        thumb: helpers.preservica_thumbnail_url(doc)
      }
    end
  end
end
