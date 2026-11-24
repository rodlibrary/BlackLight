# Interface prototype

Screenshots of the Rod Library Digital Collections interface prototype. The header links are About, Bookmarks and History. They're
taken from the clickable design canvas, where reviewers can try the facets,
sorting, list/gallery view and the collection tree:
[Digital Collections prototype](https://claude.ai/artifact/Nt4kCfCB8Nqw7WZHaUvpCQ)
(private until shared).

All records, counts and collection names are **sample data**. Styling follows
UNI's brand: Panther Purple and Goldenrod, with headings in Bookmania (Georgia
fallback) and text in Proxima Nova (Figtree fallback). These screenshots were
rendered without web fonts, so they use the system fallbacks.

| Screen | What it shows |
| --- | --- |
| [01-home.png](01-home.png) | Search box; the two top-level Preservica folders (Special Collections & University Archives, Institutional Repository) with their collections; featured collections; "Browse by" facets (Area, Department, Collection, Name, Type of Resource, Genre, Subject, Date) |
| [02-search-results.png](02-search-results.png) | Results for "flood" with facets, removable filter chips, sorting, and breadcrumbs showing where each record sits in Preservica |
| [03-collection.png](03-collection.png) | A collection page: breadcrumbs, "Browse all items", search within the collection, the folder tree of series, what's in it by type, and collection details |
| [04-item-photograph-handoff.png](04-item-photograph-handoff.png) | An item page for a photograph, with the hand-off to Preservica: thumbnail and an "Open in Preservica" button to the item in Universal Access |
| [05-item-thesis-handoff.png](05-item-thesis-handoff.png) | The same page for an Institutional Repository thesis, showing the Department field from DCDS_local |
| [06-about.png](06-about.png) | The About page, linked from the header: the library's text from the Universal Access About page, the two areas, how viewing works, a placeholder for the use policy, and the contact email |

## Access model: hand-off to Preservica

Digital Collections indexes metadata and a small thumbnail. The files stay in
Preservica. Item pages link to the item in Rod Library's Universal Access
portal, set in `config.yaml`:

```yaml
landing_url_template: "https://uni.access.preservica.com/portal/en-US/asset/sdb%3AIO%7C{uuid}"
```
