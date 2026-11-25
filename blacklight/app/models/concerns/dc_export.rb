# frozen_string_literal: true

# The record's Dublin Core, as Preservica's oai_dc (see MetadataExport): /catalog/<id>.dc.
module DcExport
  def self.extended(document)
    format = MetadataExport::FORMATS[:dc]
    document.will_export_as(format.name, format.content_type)
  end

  def export_as_dc
    self[MetadataExport::FORMATS[:dc].field]
  end
end
