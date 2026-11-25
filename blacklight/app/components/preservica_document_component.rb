# frozen_string_literal: true

# Record page (config.show.document_component): Blacklight's document component
# with breadcrumbs above the title, for folders the collection's contents, and
# metadata downloads (MODS, Dublin Core) for records that have them.
class PreservicaDocumentComponent < Blacklight::DocumentComponent
  def before_render
    unless header
      with_header do
        render BreadcrumbComponent.new(document: @document)
      end
    end
    item_map = ItemMapComponent.new(document: @document)
    if item_map.render?
      with_metadata_section do
        render item_map
      end
    end
    if @document['entity_type_ssi'] == 'folder'
      with_metadata_section do
        render CollectionContentsComponent.new(document: @document)
      end
    end
    metadata_download = MetadataDownloadComponent.new(document: @document)
    if metadata_download.render?
      with_metadata_section do
        render metadata_download
      end
    end
    super
  end
end
