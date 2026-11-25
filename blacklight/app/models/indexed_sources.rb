# frozen_string_literal: true

# Which source systems (Preservica, MuseumPlus, ScholarWorks, Janeway, Archive-It) have records
# in the search index, read from the source_ssi facet. The About page's Technology section lists
# a system only once its records are here, so adding a source updates the page without an edit.
#
# Order and wording come from config/locales (preservica.about.systems). A source in the index
# with no wording there is left off (and logged), so the page never shows a raw machine name.
#
# DC_SOURCES=preservica,museumplus overrides the index (for staging, or while Solr is down).
class IndexedSources
  CACHE_KEY = 'digital_collections/indexed_sources'
  FALLBACK = %w[preservica].freeze

  def self.list(config = CatalogController.blacklight_config)
    override = parse_env(ENV.fetch('DC_SOURCES', nil))
    return override unless override.empty?

    Rails.cache.fetch(CACHE_KEY, expires_in: 3600) { from_index(config) }
  rescue StandardError => e
    Rails.logger.warn("IndexedSources: #{e.class}: #{e.message}; using #{FALLBACK.join(', ')}")
    FALLBACK
  end

  def self.from_index(config)
    response = config.repository.connection.get(
      'select',
      params: { q: '*:*', rows: 0, facet: true, 'facet.field': 'source_ssi', 'facet.mincount': 1, 'facet.limit': -1 }
    )
    names = parse_facet(response)
    names.empty? ? FALLBACK : names
  end

  # Solr's facet list is flat: [name, count, name, count, ...].
  def self.parse_facet(response)
    flat = response.dig('facet_counts', 'facet_fields', 'source_ssi') || []
    flat.each_slice(2).filter_map { |name, count| name.to_s if count.to_i.positive? }
  end

  def self.parse_env(value)
    value.to_s.split(',').map(&:strip).reject(&:empty?)
  end

  # The systems to describe, in the locale's order, with their wording.
  def self.systems(present = list)
    wording = I18n.t('preservica.about.systems', default: {})
    unknown = present - wording.keys.map(&:to_s)
    Rails.logger.info("IndexedSources: no About wording for #{unknown.join(', ')}") if unknown.any?
    wording.select { |key, _| present.include?(key.to_s) }.values
  end
end
