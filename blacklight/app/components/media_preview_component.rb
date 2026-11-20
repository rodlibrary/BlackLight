# frozen_string_literal: true

# Preview shown above a record's metadata (config.show.document_embed_component).
#
# The ingest pipeline decides the media type (media_type_ssi) and only stores
# http(s) URLs, so this component doesn't guess from file names. URLs are
# checked again here because the index is the boundary between Preservica and
# the public site.
#
# Order: IIIF manifest (embedded in IIIF_VIEWER_URL if set), access copy from
# media_url_template, then the Preservica thumbnail as a still preview.
class MediaPreviewComponent < Blacklight::Component
  YOUTUBE = %r{\Ahttps://(?:www\.)?(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/)([\w-]{11})}
  VIMEO = %r{\Ahttps://(?:www\.)?vimeo\.com/(\d+)}

  def initialize(presenter:, document_counter: nil, **)
    super()
    @document = presenter.document
  end

  def render?
    iiif_manifest.present? || (media_url.present? && media_type.present?) || thumbnail_url.present?
  end

  # Universal Viewer, Mirador or another viewer that takes the manifest URL at
  # the end of IIIF_VIEWER_URL, e.g. https://uv-v4.netlify.app/#?manifest=
  def iiif_viewer_src
    viewer = safe(ENV.fetch('IIIF_VIEWER_URL', nil))
    return unless viewer && iiif_manifest

    viewer + CGI.escape(iiif_manifest)
  end

  def thumbnail_url
    helpers.preservica_thumbnail_url(@document)
  end

  def landing_url
    safe(@document['url_ssi'])
  end

  def media_url
    safe(@document['media_url_ssi'])
  end

  def media_type
    @document['media_type_ssi']
  end

  def iiif_manifest
    safe(@document['iiif_manifest_ssi'])
  end

  def captions_url
    safe(@document['captions_url_ssi'])
  end

  def title
    Array(@document['title_tesim']).first.to_s
  end

  def youtube_id
    media_url.to_s[YOUTUBE, 1]
  end

  def vimeo_id
    media_url.to_s[VIMEO, 1]
  end

  private

  def safe(value)
    url = Array(value).first.to_s.strip
    uri = URI.parse(url)
    uri.is_a?(URI::HTTP) && uri.host.present? ? url : nil
  rescue URI::InvalidURIError
    nil
  end
end
