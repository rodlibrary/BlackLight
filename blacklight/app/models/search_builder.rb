# frozen_string_literal: true

# Replaces the SearchBuilder Blacklight generates. Adds two map steps:
#   add_map_area  - "Search this area": ?bbox=west,south,east,north limits results
#                   to records whose coordinates fall inside the box.
#   only_mapped   - used by the Map page: only records that have coordinates.
class SearchBuilder < Blacklight::SearchBuilder
  include Blacklight::Solr::SearchBuilderBehavior

  self.default_processor_chain += [:add_map_area]

  NUMBER = /\A-?\d{1,3}(\.\d+)?\z/

  def add_map_area(solr_parameters)
    box = self.class.parse_bbox(blacklight_params[:bbox])
    return unless box

    west, south, east, north = box
    # Solr spatial range query on the RPT field: [lat,lon TO lat,lon], lower-left to upper-right.
    solr_parameters.append_filter_query("coordinates_srpt:[#{south},#{west} TO #{north},#{east}]")
  end

  def only_mapped(solr_parameters)
    solr_parameters.append_filter_query('has_coordinates_bsi:true')
  end

  # [west, south, east, north] as floats, or nil if the value isn't a valid box.
  def self.parse_bbox(value)
    parts = value.to_s.split(',')
    return unless parts.size == 4 && parts.all? { |p| p.strip.match?(NUMBER) }

    west, south, east, north = parts.map(&:to_f)
    return unless [west, east].all? { |x| x.between?(-180, 180) } && [south, north].all? { |y| y.between?(-90, 90) }
    return unless south <= north && west <= east

    [west, south, east, north]
  end
end
