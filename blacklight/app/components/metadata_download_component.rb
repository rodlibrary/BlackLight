# frozen_string_literal: true

# "Download metadata (MODS XML)" on a record page, for records the ingest
# stored MODS for (ModsExport). The file comes from /catalog/<id>.mods.
class MetadataDownloadComponent < Blacklight::Component
  def initialize(document:)
    super()
    @document = document
  end

  def render?
    @document.exports_as?(:mods)
  end

  def url
    helpers.solr_document_path(@document, format: :mods)
  end

  def filename
    ModsExport.filename(@document)
  end

  def heading_id
    "metadata-download-#{@document.id.parameterize}-heading"
  end
end
