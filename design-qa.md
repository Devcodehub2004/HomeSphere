# HomeSphere graphite dashboard — design QA

final result: passed

## Target and scope

Selected visual truth: reference.png, the user's first supplied storage-dashboard
image. This is the approved adaptation of its charcoal/silver dashboard into the
existing HomeSphere personal-cloud MVP, preserving working file actions and adding
a usable file manager. It is not a pixel-for-pixel clone of blockchain branding,
pricing, invented capacity, or decorative telemetry.

Implementation: http://localhost:5173, /home/dev/projects/homesphere/frontend.
Evidence: comparison.png (source and current implementation together), desktop.png,
reference-size.png, mobile.png, mobile-preview.png. comparison-before.png records
the earlier spacing problem.

## Normalization and state

Reference pixels: 1024 × 762. Matching browser CSS viewport: 1024 × 762, normal
browser zoom, nominal density 1. The capture excludes the native scrollbar and is
1009 pixels wide. comparison.png places the original 1024-pixel reference next to
the 1009-pixel browser capture without stretching the dashboard composition.
Desktop verification also used 1440 × 1000; mobile used 375 × 812 with no document
horizontal overflow. The reference includes a surrounding gray mockup stage;
HomeSphere uses the gray stage as its page background and continues below the
reference's original single-screen concept for actual file management.

State: live API data, one stored README.md, 4.2 KiB. The reference's invented GB
figures are intentionally replaced with real totals. No stored file was changed
or deleted during browser checks. Mobile preview uses the existing README.

## Findings and fixes

1. [P2, fixed] Mobile sphere overlapped the Cloud title. Moved and reduced its
   mobile canvas slot. mobile.png shows distinct readable text and sphere regions.
2. [P2, fixed] Compact desktop overview placed the volume readout over the Cloud
   title. Hid redundant introductory text at desktop widths, separated the title
   and CTA, and re-captured at the reference viewport. comparison.png and the DOM
   bounding boxes confirm no overlap after the fix.
3. [P2, fixed] Mobile preview's icon-only Download link had no accessible name.
   Added an explicit per-file accessible label.

No actionable P0/P1/P2 findings remain for the agreed adaptation.

## Fidelity surfaces

- Typography: Space Grotesk with system fallback; restrained geometric headings,
  uppercase tracking for secondary labels, normal-case readable file names.
  The Cloud/storage lockup and right-panel hierarchy match the reference's intent.
- Layout: rounded dark frame on gray canvas; main overview and contrasting right
  storage panel; dominant faceted sphere and readable left controls. A functional
  file manager follows the overview. Mobile stacks the storage panel below files.
- Color: charcoal #1c2325, panel #303a40, desaturated silver/blue-gray surfaces,
  pale text and silver upload CTA. Strong focus rings and clear destructive states.
- Assets: actual interactive Three.js faceted volume with edges and joint nodes,
  as requested, and consistent Lucide line icons. No raster stand-ins for 3D.
  The sphere intentionally omits the reference's tiny decorative face markings.
- Copy/data: HomeSphere branding, local-volume language, actual file counts and
  type-by-type byte totals. No fake quota, capacity, pricing or blockchain claims.

The full-size comparison makes the primary controls readable; source details
smaller than a few pixels are treated as decorative rather than literal text to
reproduce. The selected image provides no mobile or file-preview state; these are
product adaptations checked separately in mobile.png and mobile-preview.png.

## Interaction checks

- Live listing and storage totals load from the existing API.
- Grid/list toggles, search, empty results, clearing search, category filtering,
  right-panel shortcuts, and clearing filters passed.
- README preview opens and displays contents; Escape closes it.
- Rename dialog and delete confirmation open and cancel correctly.
- Sphere pause/resume and rotate controls passed; scene follows pointer input.
- Existing upload/download/rename/delete request implementations were retained.
  Destructive operations were not executed against user files during this styling
  pass. The earlier backend lifecycle tests remain separate validation.
- Reduced-motion handling pauses the actual 3D scene; hidden/offscreen work pauses.
- Browser log check: no runtime errors; upstream THREE.Clock deprecation warnings.

## Build/checks and residual polish

Production build passed. Source lint: zero errors, two pre-existing React advisory
warnings about the shared preview-type export and synchronous loading-state setup
in the initial effect. The lazy Three.js chunk remains approximately 0.91 MB before
compression. These are follow-up maintenance items, not blocked functionality.

Backend, migrations, Docker volumes and existing file data were not changed.
Original frontend files are backed up under .homesphere-backups/graphite-*.

## Implementation checklist

- [x] Preserve the API integration and preview behavior.
- [x] Apply the chosen graphite/silver direction and interactive sphere.
- [x] Render actual storage composition and file counts.
- [x] Correct responsive and accessible-name issues found during inspection.
- [x] Compare the source and final render together and inspect mobile separately.
- [x] Compile successfully and inspect browser logs.
