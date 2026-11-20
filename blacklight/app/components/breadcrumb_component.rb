# frozen_string_literal: true

# "University Archives › Flood Relief Records › Series 2" above a record.
#
# The ingest writes ancestor ids and titles root first, in two parallel fields,
# and only for public folders. Each crumb opens the folder's collection page;
# set PRESERVICA_FOLDER_RECORDS=false if folders aren't indexed
# (include_folders: false) and the crumbs link to a search within the folder.
class BreadcrumbComponent < Blacklight::Component
  def initialize(document:)
    super()
    @document = document
  end

  def render?
    crumbs.any?
  end

  def crumbs
    @crumbs ||= begin
      ids = Array(@document['ancestor_ids_ssim'])
      titles = Array(@document['ancestor_titles_ssm'])
      ids.size == titles.size ? ids.zip(titles) : []
    end
  end

  def path_for(id)
    if ENV.fetch('PRESERVICA_FOLDER_RECORDS', 'true') == 'false'
      helpers.within_folder_path(id)
    else
      helpers.solr_document_path(id)
    end
  end
end
