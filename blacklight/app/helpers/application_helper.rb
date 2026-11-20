# frozen_string_literal: true

module ApplicationHelper
  # Tags allowed in harvested descriptions and notes. Everything else (scripts,
  # iframes, event handlers, styles) is stripped: metadata comes from Preservica
  # and must never be rendered with html_safe.
  RICH_TEXT_TAGS = %w[p br em i strong b u sub sup ul ol li a blockquote].freeze
  RICH_TEXT_ATTRIBUTES = %w[href].freeze
  # The ingest names cached thumbnails <uuid>.<ext>; anything else is ignored.
  THUMBNAIL_FILE = /\A[0-9a-z-]+\.(jpg|png|gif|webp)\z/

  # Returns the URL only when it is absolute http(s).
  def safe_url(value)
    uri = URI.parse(value.to_s.strip)
    uri.is_a?(URI::HTTP) && uri.host.present? ? uri.to_s : nil
  rescue URI::InvalidURIError
    nil
  end

  # URL of a record's thumbnail: a public thumbnail URL from the index, or the
  # file the ingest cached under public/thumbnails (or THUMBNAIL_BASE_URL).
  def preservica_thumbnail_url(document)
    url = Array(document['thumbnail_url_ssm']).filter_map { |u| safe_url(u) }.first
    return url if url

    file = document['thumbnail_file_ssi'].to_s
    return unless file.match?(THUMBNAIL_FILE)

    base = ENV.fetch('THUMBNAIL_BASE_URL', '/thumbnails').chomp('/')
    "#{base}/#{file}"
  end

  # thumbnail_method for search results.
  def preservica_thumbnail(document, image_options = {})
    url = preservica_thumbnail_url(document)
    return unless url

    image_tag(url, { alt: '', loading: 'lazy', class: 'img-thumbnail' }.merge(image_options))
  end

  # Facet helper: show a folder's title instead of its id in search constraints.
  def folder_title(id)
    @folder_titles ||= {}
    @folder_titles[id] ||= begin
      doc = blacklight_config.repository.find(id).documents.first
      Array(doc && doc['title_tesim']).first.presence || id
    rescue Blacklight::Exceptions::RecordNotFound, Blacklight::Exceptions::InvalidRequest
      id
    end
  end

  # Index field helper: "University Archives › Flood Relief Records".
  def render_part_of(value:, **)
    safe_join(Array(value), ' › ')
  end

  # Field helper: sanitized HTML for descriptions and notes.
  def render_rich_text(value:, **)
    safe_join(Array(value).map do |v|
      content_tag(:div, sanitize(simple_format(v.to_s, {}, sanitize: false),
                                 tags: RICH_TEXT_TAGS, attributes: RICH_TEXT_ATTRIBUTES),
                  class: 'rich-text')
    end)
  end

  # Field helper: plain-text summary in search results.
  def render_summary(value:, **)
    truncate(strip_tags(Array(value).first.to_s), length: 300, separator: ' ')
  end

  # Field helper: link a URL field, dropping anything that isn't http(s).
  def render_safe_link(value:, **)
    links = Array(value).filter_map do |v|
      url = safe_url(v)
      link_to(url, url, target: '_blank', rel: 'noopener noreferrer') if url
    end
    safe_join(links, tag.br)
  end

  # Field helper: DOI as a resolvable link.
  def render_doi_link(value:, **)
    doi = Array(value).first.to_s.sub(%r{\Ahttps?://(dx\.)?doi\.org/}i, '')
    return '' if doi.blank?

    link_to(doi, "https://doi.org/#{doi}", target: '_blank', rel: 'noopener noreferrer')
  end

  # Top-level collections for the home page, A-Z.
  def top_level_collections(limit: 24)
    response = blacklight_config.repository.search(params: {
      q: '*:*', defType: 'lucene', fq: ['entity_type_ssi:folder', 'depth_isi:0'],
      rows: limit, sort: 'title_ssort asc', facet: false, spellcheck: false,
      fl: 'id,title_tesim,abstract_tesim,thumbnail_url_ssm,thumbnail_file_ssi'
    })
    [response.documents, response.total]
  rescue Blacklight::Exceptions::ECONNREFUSED, Blacklight::Exceptions::InvalidRequest
    [[], 0]
  end

  # Search link for everything inside a folder, at any depth.
  def within_folder_path(id, **params)
    search_catalog_path({ f: { ancestor_ids_ssim: [id] } }.merge(params))
  end
end
