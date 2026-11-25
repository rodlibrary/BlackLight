# frozen_string_literal: true

# Static pages, such as About (/about). They use the site's Blacklight layout,
# so the header, search box and footer match the catalog.
class PagesController < ApplicationController
  def about
    # Technology lists the source systems that have records in the index (see IndexedSources).
    @systems = IndexedSources.systems
  end
end
