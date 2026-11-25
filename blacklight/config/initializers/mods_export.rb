# frozen_string_literal: true

# MODS downloads (app/models/concerns/mods_export.rb): /catalog/<id>.mods for
# records the ingest stored MODS for (mods_download in config.yaml).
Mime::Type.register 'application/mods+xml', :mods unless Mime[:mods]

# to_prepare, so the extension is registered again when development reloads SolrDocument.
Rails.application.config.to_prepare do
  SolrDocument.use_extension(ModsExport) { |document| ModsExport.applies?(document) }
end
