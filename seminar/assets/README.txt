CANVA PAGES — how to export them
================================

build_deck.py inserts seven pages from the Group 11 Canva deck into our
presentation. It looks for these exact filenames in THIS folder:

    canva-08.png     Canva page 8   "LOG DATA"          (the wall of log text)
    canva-09.png     Canva page 9   "MEAN TIME TO RECOVERY"
    canva-10.png     Canva page 10  "INCORPORATE AI INTO THE SDLC"
    canva-11.png     Canva page 11  "CI/CD OPTIMIZATION"  (base diagram)
    canva-12.png     Canva page 12  + Test Impact Analysis callout
    canva-13.png     Canva page 13  + Build Failure Prediction callout
    canva-14.png     Canva page 14  + Pipeline Self-Diagnosis callout


HOW TO EXPORT
-------------

1. Open the Canva design.
2. Share  ->  Download.
3. File type: PNG.
4. Tick "Select pages" and choose ONLY pages 8, 9, 10, 11, 12, 13, 14.
5. Set Size to 2x if the option is available. Bigger is better for a projector.
6. Download. You get a .zip with files named something like
   "Presentation - 8.png", "Presentation - 9.png", ...
7. Unzip and rename them to canva-08.png ... canva-14.png, then put them here.

Then run:

    py build_deck.py

It will report "All 7 Canva pages inserted."


NOTES
-----

- The deck still builds if some files are missing. It just skips those slides
  and tells you which ones it could not find. So you can add them one at a
  time.

- Canva pages are 16:9, the same shape as our slides, so they land full-bleed
  with no borders. If a page comes out a different shape, the script centres it
  and leaves white margins rather than stretching it.

- JPG works too, but change the extension in build_deck.py to match, or just
  rename the file to .png only if it really is a PNG. Do not rename a .jpg to
  .png — python-pptx reads the actual file header and will refuse it.

- Ask your friend in Group 11 before using their slides in a graded
  presentation, and credit them. Requirement section 6 says: "clearly credit
  any external source, image, or generated content." A line on the references
  slide is enough, e.g. "Diagrams on slides 7, 9, 12, 14, 16, 18, 20 adapted
  from the Group 11 seminar deck, used with permission."
