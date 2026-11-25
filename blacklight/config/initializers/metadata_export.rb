# frozen_string_literal: true

# Metadata downloads (app/models/concerns/metadata_export.rb): /catalog/<id>.mods
# and /catalog/<id>.dc for records the ingest stored them for.
Mime::Type.register 'application/mods+xml', :mods unless Mime[:mods]
# Dublin Core is plain XML; an alias keeps 'application/xml' requests going to :xml.
Mime::Type.register_alias 'application/xml', :dc unless Mime[:dc]

# to_prepare, so the extensions are registered again when development reloads SolrDocument.
Rails.application.config.to_prepare do
  SolrDocument.use_extension(ModsExport) { |document| MetadataExport.applies?(document, :mods) }
  SolrDocument.use_extension(DcExport) { |document| MetadataExport.applies?(document, :dc) }
end
