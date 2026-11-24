# frozen_string_literal: true

# "Map" button beside sort and per-page above search results: opens the Map
# page (/map) for the same search. Registered as a results collection tool,
# so it takes the keyword arguments Blacklight passes to those.
class MapLinkComponent < Blacklight::Component
  def initialize(action: nil, document: nil, options: {}, url_opts: {}, link_classes: nil, **)
    super()
  end

  def call
    params = helpers.search_state.params_for_search.except(:controller, :action, :page, :per_page, :view)
    link_to helpers.map_path(params), class: 'btn btn-outline-secondary btn-sm d-inline-flex align-items-center gap-1' do
      safe_join([icon, helpers.t('preservica.map.link')])
    end
  end

  private

  def icon
    tag.svg(width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 2,
            'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': true) do
      tag.path(d: 'M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z') + tag.path(d: 'M9 4v14M15 6v14')
    end
  end
end
