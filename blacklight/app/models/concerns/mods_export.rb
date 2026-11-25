# frozen_string_literal: true

# The record's MODS (see MetadataExport): /catalog/<id>.mods.
module ModsExport
  def self.extended(document)
    format = MetadataExport::FORMATS[:mods]
    document.will_export_as(format.name, format.content_type)
  end

  def export_as_mods
    self[MetadataExport::FORMATS[:mods].field]
  end
end
