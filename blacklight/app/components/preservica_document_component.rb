# frozen_string_literal: true

# Record page (config.show.document_component): Blacklight's document component
# with breadcrumbs above the title and, for folders, the collection's contents.
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
    super
  end
end
