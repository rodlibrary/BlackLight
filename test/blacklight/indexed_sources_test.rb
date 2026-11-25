# frozen_string_literal: true

# Unit test for IndexedSources, outside Rails, with plain-Ruby stand-ins for Rails.cache,
# Rails.logger, I18n (reading the real locale file) and the Blacklight repository.
# Run: ruby test/blacklight/indexed_sources_test.rb
require 'minitest/autorun'
require 'logger'
require 'yaml'

module Rails
  class NullCache
    def fetch(*) = yield
  end

  def self.cache = NullCache.new
  def self.logger = Logger.new(nil)
end

ROOT = File.expand_path('../..', __dir__)

module I18n
  LOCALE = YAML.load_file(File.join(ROOT, 'blacklight/config/locales/preservica.en.yml'), symbolize_names: true)

  def self.t(key, default: nil)
    key.split('.').map(&:to_sym).reduce(LOCALE[:en]) { |h, k| h.is_a?(Hash) ? h[k] : nil } || default
  end
end
require File.join(ROOT, 'blacklight/app/models/indexed_sources')

class IndexedSourcesTest < Minitest::Test
  FakeConfig = Struct.new(:repository)
  FakeRepo = Struct.new(:connection)

  class FakeSolr
    def initialize(flat = nil, error: nil)
      @flat = flat
      @error = error
    end

    def get(_path, params:)
      raise @error if @error

      { 'facet_counts' => { 'facet_fields' => { params[:'facet.field'] => @flat } } }
    end
  end

  def config(flat = nil, error: nil) = FakeConfig.new(FakeRepo.new(FakeSolr.new(flat, error: error)))

  def teardown = ENV.delete('DC_SOURCES')

  def test_reads_sources_with_records_from_the_facet
    assert_equal %w[preservica scholarworks], IndexedSources.list(config(['preservica', 7, 'scholarworks', 3, 'museumplus', 0]))
  end

  def test_falls_back_to_preservica_when_the_index_is_empty_or_down
    assert_equal %w[preservica], IndexedSources.list(config([]))
    assert_equal %w[preservica], IndexedSources.list(config(error: RuntimeError.new('connection refused')))
  end

  def test_environment_overrides_the_index
    ENV['DC_SOURCES'] = 'preservica, archiveit'
    assert_equal %w[preservica archiveit], IndexedSources.list(config(['preservica', 7]))
  end

  def test_systems_follow_the_locale_order_and_skip_unknown_sources
    names = IndexedSources.systems(%w[archiveit preservica mystery museumplus]).map { |s| s[:name] }
    assert_equal ['Preservica', 'MuseumPlus', 'Archive-It'], names
  end

  def test_every_system_has_a_name_link_and_text
    IndexedSources.systems(%w[preservica museumplus scholarworks janeway archiveit]).each do |s|
      refute_empty s[:name].to_s
      refute_empty s[:text].to_s
      assert_match %r{\Ahttps://}, s[:url]
    end
  end
end
