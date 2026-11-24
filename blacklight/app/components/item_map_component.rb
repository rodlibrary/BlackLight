# frozen_string_literal: true

# A map on a record's page when the record has coordinates (a pin) and/or a
# IIIF Georeference Annotation (a scanned map warped over the basemap with
# Allmaps). Leaflet and the Allmaps plugin load as modules from jsDelivr.
class ItemMapComponent < Blacklight::Component
  ALLMAPS_VIEWER = 'https://viewer.allmaps.org/?url='

  def initialize(document:)
    super()
    @document = document
  end

  def render?
    points.any? || georeference_url.present?
  end

  def points
    @points ||= Array(@document['coordinates_ssm']).filter_map do |pair|
      lat, lon = pair.to_s.split(',').map { |v| Float(v, exception: false) }
      [lat, lon] if lat && lon
    end
  end

  def georeference_url
    helpers.safe_url(@document['georeference_url_ssi'])
  end

  def allmaps_viewer_url
    ALLMAPS_VIEWER + CGI.escape(georeference_url) if georeference_url
  end

  def tile_url
    ENV.fetch('MAP_TILE_URL', 'https://tile.openstreetmap.org/{z}/{x}/{y}.png')
  end

  def tile_attribution
    ENV.fetch('MAP_TILE_ATTRIBUTION', '&copy; OpenStreetMap contributors')
  end

  def map_id
    "item-map-#{@document.id.parameterize}"
  end
end
