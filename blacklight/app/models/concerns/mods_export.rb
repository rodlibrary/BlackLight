# frozen_string_literal: true

# MODS download for records harvested with MODS: a SolrDocument extension
# (registered in config/initializers/mods_export.rb), so Blacklight serves
# /catalog/<id>.mods and lists it as a <link rel="alternate"> on the record page.
#
# The ingest stores each public record's MODS, as Preservica's OAI-PMH provider
# returned it, in mods_xml_ss (stored, not indexed). Elements outside the MODS
# namespace, and any listed in mods_download_strip, are dropped before it is
# stored (ingest/preservica/metadata.py#mods_document). Records with only
# Dublin Core, and folders known only from the Entity API, have no MODS, so
# they get no download and /catalog/<id>.mods answers 406.
module ModsExport
  FIELD = 'mods_xml_ss'
  CONTENT_TYPE = 'application/mods+xml'
  MODS_NS = 'http://www.loc.gov/mods/v3'
  DECLARATION = /\A\s*<\?xml[^>]*\?>\s*/

  def self.extended(document)
    document.will_export_as(:mods, CONTENT_TYPE)
  end

  def self.applies?(document)
    !document[FIELD].to_s.strip.empty?
  end

  # File name for the download: the record id is lowercase letters, digits, '.', '_' and '-'.
  def self.filename(document)
    "#{document.id}-mods.xml"
  end

  # The records on a page of search results that have MODS, as one <mods:modsCollection>.
  def self.collection(documents)
    records = documents.select { |d| d.respond_to?(:export_as_mods) }
                       .map { |d| d.export_as_mods.sub(DECLARATION, '').strip }
    [%(<?xml version="1.0" encoding="UTF-8"?>), %(<mods:modsCollection xmlns:mods="#{MODS_NS}">),
     *records, '</mods:modsCollection>', ''].join("\n")
  end

  def export_as_mods
    self[FIELD]
  end
end
