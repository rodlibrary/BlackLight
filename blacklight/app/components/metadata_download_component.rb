# frozen_string_literal: true

# "Download metadata" buttons on a record page (items, folders and collections
# alike): one per format the ingest stored for the record (MetadataExport).
class MetadataDownloadComponent < Blacklight::Component
  def initialize(document:)
    super()
    @document = document
  end

  def render?
    formats.any?
  end

  def formats
    @formats ||= MetadataExport.available(@document)
  end

  def url(name)
    helpers.solr_document_path(@document, format: name)
  end

  def filename(name)
    MetadataExport.filename(@document, name)
  end

  def content_type(name)
    MetadataExport::FORMATS.fetch(name).content_type
  end

  def heading_id
    "metadata-download-#{@document.id.parameterize}-heading"
  end
end
