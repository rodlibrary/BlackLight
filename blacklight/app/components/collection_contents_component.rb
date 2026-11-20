# frozen_string_literal: true

# On a folder's record page: its subfolders, how many items it holds (at any
# depth), and a "search within this collection" box.
#
# Queries go straight to the repository. The index only ever holds public
# records, so there is nothing to filter out here.
class CollectionContentsComponent < Blacklight::Component
  SUBFOLDER_LIMIT = 50

  def initialize(document:)
    super()
    @document = document
  end

  def id
    @document.id
  end

  def title
    Array(@document['title_tesim']).first.to_s
  end

  def subfolders
    @subfolders ||= query(['{!term f=parent_id_ssi v=$folder}', 'entity_type_ssi:folder'],
                          rows: SUBFOLDER_LIMIT, sort: 'title_ssort asc', fl: 'id,title_tesim')
  end

  def item_count
    @item_count ||= query(['{!term f=ancestor_ids_ssim v=$folder}', 'entity_type_ssi:asset'], rows: 0).total
  end

  def direct_item_count
    @direct_item_count ||= query(['{!term f=parent_id_ssi v=$folder}', 'entity_type_ssi:asset'], rows: 0).total
  end

  def subfolder_title(doc)
    Array(doc['title_tesim']).first.presence || 'Untitled folder'
  end

  def browse_all_path
    helpers.within_folder_path(id, f: { ancestor_ids_ssim: [id], entity_type_ssim: ['Item'] })
  end

  def browse_direct_path
    helpers.search_catalog_path(f: { parent_id_ssi: [id], entity_type_ssim: ['Item'] })
  end

  private

  # Folder ids go in a separate parameter ($folder) so they are never parsed as query syntax.
  def query(fq, **params)
    helpers.blacklight_config.repository.search(params: {
      q: '*:*', defType: 'lucene', fq: fq, folder: id, facet: false, spellcheck: false
    }.merge(params))
  end
end
