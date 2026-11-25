# frozen_string_literal: true

# Metadata downloads: a record's MODS and Dublin Core as XML files, for records
# the ingest stored them for (mods_download and dc_download in config.yaml).
#
# The ingest stores each public record's metadata, as Preservica's OAI-PMH
# provider returned it, in stored-only Solr fields. Elements outside the
# format's namespace, and any listed in *_download_strip, are dropped first
# (ingest/preservica/metadata.py#metadata_document). A record without a format
# gets no button for it, and /catalog/<id>.<format> answers 406.
#
# Each format is a SolrDocument extension (ModsExport, DcExport; registered in
# config/initializers/metadata_export.rb), so Blacklight serves
# /catalog/<id>.mods and /catalog/<id>.dc and lists them as
# <link rel="alternate"> on the record page.
module MetadataExport
  Format = Struct.new(:name, :field, :content_type, :suffix, keyword_init: true)

  FORMATS = {
    mods: Format.new(name: :mods, field: 'mods_xml_ss', content_type: 'application/mods+xml', suffix: 'mods'),
    dc: Format.new(name: :dc, field: 'dc_xml_ss', content_type: 'application/xml', suffix: 'dc')
  }.freeze

  MODS_NS = 'http://www.loc.gov/mods/v3'
  DECLARATION = /\A\s*<\?xml[^>]*\?>\s*/

  def self.applies?(document, name)
    !document[FORMATS.fetch(name).field].to_s.strip.empty?
  end

  # The formats this record can be downloaded in, in button order.
  def self.available(document)
    FORMATS.keys.select { |name| document.exports_as?(name) }
  end

  # File name for a download: the record id is lowercase letters, digits, '.', '_' and '-'.
  def self.filename(document, name)
    "#{document.id}-#{FORMATS.fetch(name).suffix}.xml"
  end

  # The records on a page of search results that have MODS, as one <mods:modsCollection>.
  # Dublin Core has no standard collection element, so it is offered per record only.
  def self.mods_collection(documents)
    records = documents.select { |d| d.exports_as?(:mods) }
                       .map { |d| d.export_as_mods.sub(DECLARATION, '').strip }
    [%(<?xml version="1.0" encoding="UTF-8"?>), %(<mods:modsCollection xmlns:mods="#{MODS_NS}">),
     *records, '</mods:modsCollection>', ''].join("\n")
  end
end
