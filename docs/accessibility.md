# Accessibility

Digital Collections aims to meet **WCAG 2.1 Level AA**. That is the standard the U.S. Department
of Justice adopted for public universities under ADA Title II. UNI, as a large public entity,
has until **April 26, 2027** under the April 2026 interim final rule. Confirm the current date
and any exceptions with UNI's accessibility office.

## What was checked (November 2026)

| Check | How | Result |
|---|---|---|
| Automated rules (WCAG 2.0/2.1 A and AA, plus best practice) | axe-core 4 on all seven prototype screens and every item-page variant | No violations after fixes |
| Keyboard: skip link, focus order, visible focus | Tabbing through each screen; checking every focusable element shows a focus style | Skip link first on every page; every control shows focus |
| Reflow at 320 px (1.4.10) | Page width at a 320 px viewport | No sideways scrolling after fixes |
| Text spacing (1.4.12) | WCAG's spacing override, checking for clipped text | Nothing clipped except intentionally hidden screen-reader text |
| Control boundaries (1.4.11) | Border contrast of search boxes and menus | Raised to over 3:1 |
| Map page keyboard use (2.1.1) | Leaflet with real pins in a browser: Tab to pins, Enter opens, Escape closes | Works; focus moves into the popup and back to the pin |
| Rails views and components | Code review of the overlay in `blacklight/` | Fixes below |

## Changes made

**Prototype and code**

- **Skip link** on every page: the prototype now has one; Blacklight's layout already provides it.
- **Focus:** a 3px focus ring in Panther Purple, and gold on the dark footer.
- **Reflow:** the header search wraps at narrow widths. Grids and the footer no longer force
  sideways scrolling, and long identifiers wrap.
- **Control borders:** search boxes and menus now have borders with enough contrast.
- **Landmarks:** all content sits inside header, main or footer landmarks.
- **Search page:** it has a page heading. The "remove search" button's accessible name
  includes its visible text (2.5.3). Selected filters say they're selected. "Show all" says
  which filter it expands, and reports whether it's open.
- **Page titles** name the page and the site (2.4.2).
- **Links that open a new tab** say so to screen readers (helper `new_tab_link_to`).
- **Map page:** pins can be reached with Tab and opened with Enter, and each is named after its
  record. A popup takes focus, and Escape returns focus to the pin. A "Skip past the map" link
  and keyboard instructions sit above the map, and the list view is linked below it.
- **Item maps:** pins aren't clickable controls, and the coordinates are shown as text.
- **Reduced motion:** animations are switched off when the visitor's system asks for that.

## What still needs people, not tools

Automated tools catch only part of WCAG. Before launch, and after major changes:

1. **Test the running site.** Run axe (or WAVE) on staging pages: home, search results with
   filters, a collection, items of each type, Advanced search, Map, About. Blacklight's own
   markup is only covered once it's running.
2. **Screen readers:** run a short task script with NVDA and Firefox, and VoiceOver and Safari:
   search, filter, open an item, use the map list. Note anything confusing.
3. **Zoom to 200% and 400%** in a desktop browser, and use a phone at its largest text size.
4. **Content, which is the biggest part:**
   - **Alternative text:** thumbnails sit beside the item's linked title and are marked as
     decorative, and a full image on an item page is named by its title. So titles need to be
     meaningful, and images whose meaning isn't in the title need a description in MODS (an
     abstract or note).
   - **Audio and video:** prerecorded media needs captions (1.2.2), and video needs audio
     description or a text alternative where visuals carry meaning (1.2.5). Audio needs a
     transcript (1.2.1). The site shows captions and transcript links when the metadata
     provides them.
   - **PDFs and scanned text** need a text layer (OCR) and, for born-digital documents, tagging.
   - **Viewers outside this site:** Preservica's Universal Access portal, the IIIF viewer
     and Allmaps are covered by the same rule when UNI provides them. Ask Preservica for its
     accessibility conformance report (VPAT), and check any IIIF viewer before turning it on.
5. **Exceptions:** the rule has narrow exceptions, for example for archived web content and
   for some documents posted before the compliance date. Whether any collection qualifies is
   a question for UNI's accessibility office, not an assumption to build on.

## How to re-run the checks

The prototype checks use Playwright and axe-core:

```bash
npm i axe-core@4
# then load each page in Playwright, inject node_modules/axe-core/axe.min.js and run
# axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa']}})
```

For the running site, the axe DevTools browser extension or `@axe-core/cli` against staging
URLs does the same.
