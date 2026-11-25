# frozen_string_literal: true

# Unit test for ModsExport, outside Rails, with a plain-Ruby stand-in for SolrDocument.
# Run: ruby test/blacklight/mods_export_test.rb
require 'minitest/autorun'
require 'rexml/document'

ROOT = File.expand_path('../..', __dir__)
require File.join(ROOT, 'blacklight/app/models/concerns/mods_export')

class ModsExportTest < Minitest::Test
  # Just enough of Blacklight's SolrDocument and Blacklight::Document::Export.
  class FakeDocument
    attr_reader :id, :export_formats

    def initialize(id, fields)
      @id = id
      @fields = fields
      @export_formats = {}
      extend ModsExport if ModsExport.applies?(self)
    end

    def [](key) = @fields[key]
    def will_export_as(name, type) = (@export_formats[name] = { content_type: type })
  end

  MODS = <<~XML
    <?xml version="1.0" encoding="UTF-8"?>
    <mods:mods xmlns:mods="http://www.loc.gov/mods/v3"><mods:titleInfo><mods:title>Okafor interview</mods:title></mods:titleInfo></mods:mods>
  XML

  def doc(id, mods = MODS) = FakeDocument.new(id, mods ? { 'mods_xml_ss' => mods } : {})

  def test_records_with_mods_export_it
    d = doc('preservica-a1')
    assert_equal({ mods: { content_type: 'application/mods+xml' } }, d.export_formats)
    assert_equal MODS, d.export_as_mods
    assert_equal 'preservica-a1-mods.xml', ModsExport.filename(d)
  end

  def test_records_without_mods_do_not
    [doc('preservica-a2', nil), doc('preservica-a3', "  \n")].each do |d|
      refute d.respond_to?(:export_as_mods)
      assert_empty d.export_formats
    end
  end

  def test_search_results_become_one_well_formed_collection
    xml = ModsExport.collection([doc('a'), doc('b', nil), doc('c')])
    root = REXML::Document.new(xml).root
    assert_equal ['mods', 'modsCollection'], [root.prefix, root.name]
    titles = REXML::XPath.match(root, '//mods:title', 'mods' => ModsExport::MODS_NS).map(&:text)
    assert_equal ['Okafor interview', 'Okafor interview'], titles
    assert_equal 1, xml.scan('<?xml').size
  end

  def test_empty_results_are_still_a_valid_collection
    root = REXML::Document.new(ModsExport.collection([])).root
    assert_equal 'modsCollection', root.name
    assert_empty root.elements.to_a
  end
end
