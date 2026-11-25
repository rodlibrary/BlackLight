# frozen_string_literal: true

# Unit test for the metadata downloads (MetadataExport, ModsExport, DcExport), outside Rails,
# with a plain-Ruby stand-in for SolrDocument and Blacklight::Document::Export.
# Run: ruby test/blacklight/metadata_export_test.rb
require 'minitest/autorun'
require 'rexml/document'

ROOT = File.expand_path('../..', __dir__)
%w[metadata_export mods_export dc_export].each { |f| require File.join(ROOT, "blacklight/app/models/concerns/#{f}") }

class MetadataExportTest < Minitest::Test
  class FakeDocument
    attr_reader :id, :export_formats

    def initialize(id, fields)
      @id = id
      @fields = fields
      @export_formats = {}
      extend ModsExport if MetadataExport.applies?(self, :mods)
      extend DcExport if MetadataExport.applies?(self, :dc)
    end

    def [](key) = @fields[key]
    def will_export_as(name, type) = (@export_formats[name] = { content_type: type })
    def exports_as?(name) = respond_to?("export_as_#{name}")
    def export_as(name) = send("export_as_#{name}")
  end

  MODS = <<~XML
    <?xml version="1.0" encoding="UTF-8"?>
    <mods:mods xmlns:mods="http://www.loc.gov/mods/v3"><mods:titleInfo><mods:title>Okafor interview</mods:title></mods:titleInfo></mods:mods>
  XML
  DC = <<~XML
    <?xml version="1.0" encoding="UTF-8"?>
    <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Okafor</dc:title></oai_dc:dc>
  XML

  def doc(id, mods: MODS, dc: DC)
    FakeDocument.new(id, { 'mods_xml_ss' => mods, 'dc_xml_ss' => dc }.compact)
  end

  def test_both_formats
    d = doc('preservica-a1')
    assert_equal %i[mods dc], MetadataExport.available(d)
    assert_equal({ mods: { content_type: 'application/mods+xml' }, dc: { content_type: 'application/xml' } },
                 d.export_formats)
    assert_equal MODS, d.export_as(:mods)
    assert_equal DC, d.export_as(:dc)
    assert_equal 'preservica-a1-mods.xml', MetadataExport.filename(d, :mods)
    assert_equal 'preservica-a1-dc.xml', MetadataExport.filename(d, :dc)
  end

  def test_only_the_formats_a_record_has
    assert_equal %i[dc], MetadataExport.available(doc('preservica-a2', mods: nil))
    assert_equal %i[mods], MetadataExport.available(doc('preservica-f1', dc: "  \n"))
    none = doc('preservica-f3', mods: nil, dc: nil)
    assert_empty MetadataExport.available(none)
    assert_empty none.export_formats
  end

  def test_search_results_become_one_well_formed_mods_collection
    xml = MetadataExport.mods_collection([doc('a'), doc('b', mods: nil), doc('c')])
    root = REXML::Document.new(xml).root
    assert_equal ['mods', 'modsCollection'], [root.prefix, root.name]
    titles = REXML::XPath.match(root, '//mods:title', 'mods' => MetadataExport::MODS_NS).map(&:text)
    assert_equal ['Okafor interview', 'Okafor interview'], titles
    assert_equal 1, xml.scan('<?xml').size
  end

  def test_empty_results_are_still_a_valid_collection
    root = REXML::Document.new(MetadataExport.mods_collection([])).root
    assert_equal 'modsCollection', root.name
    assert_empty root.elements.to_a
  end
end
