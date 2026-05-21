# NMR parsers — vendor support

The science profile's upload-preview modal renders 1D NMR
spectra without leaving the page. As of stream B (PRs #77 –
#82) the browser-side parser pipeline covers JCAMP-DX 5.01,
plain CSV / XY ASCII, and the vendor-specific quirks of
**Bruker TopSpin** and **Magritek SpinSolve** exports.

This document maps each file to the contract it pins.

## File map

```
openmiura/ui/v2/static/js/science/
├── nmr.js          # Top-level parser + dispatcher (parseSpectrum)
├── nmr_asdf.js     # ASDF compression decoder (H2.1)
├── nmr_csv.js      # CSV / XY plain-text parser (H2.2)
└── nmr_vendor.js   # Vendor detection helper (H2.5)
```

All four modules expose globals (`window.scienceNmr`,
`window.scienceNmrAsdf`, `window.scienceNmrCsv`,
`window.scienceNmrVendor`) — no module loader, no build step.
The upload page (`science.html`) loads them in dependency
order before `upload.js`.

## Parser pipeline

```
parseSpectrum(text)
 ├── isLikelyJcamp ? parseJcampDx
 │                    ├── (XY..XY)      — plain pairs
 │                    └── (X++(Y..Y))   — line-prefixed Y runs
 │                         └── per-line: scienceNmrAsdf.decodeAsdfLine (H2.1)
 │   ↓
 │   _brukerEnhance      (H2.3)
 │   _magritekEnhance    (H2.4)
 │   ↓ returns parsed
 └── isLikelyCsv ? scienceNmrCsv.parseCsvXy   (H2.2)
                    └── returns parsed
```

## Vendor enhancers

After the generic JCAMP parse completes, two post-processors
run unconditionally. They're no-ops on files that don't carry
their trigger headers.

### Bruker TopSpin — `_brukerEnhance` (H2.3)

| Header read | Field set | Notes |
|---|---|---|
| `##$NUC1` | `parsed.nuclei` | Strips `<...>` wrapping (`<1H>` → `1H`). |
| `##$BF1` | `parsed.bf1` | Base frequency, MHz. |
| `##XUNITS= HZ` + `##$BF1` | `parsed.xunits = 'PPM'`, every `point.x /= bf1`, `xunits_original` keeps the prior unit | Conversion runs once. |
| `##XYDATA=` repeated | `parsed.warnings[]` warning | Multi-block (real + imaginary); only the first block is rendered. |

### Magritek SpinSolve — `_magritekEnhance` (H2.4)

| Header / comment read | Field set | Notes |
|---|---|---|
| `##ORIGIN` containing `magritek` or `spinsolve` | `parsed.vendor_origin` | Verbatim. |
| `##.OBSERVE NUCLEUS` | `parsed.nuclei` | Only when Bruker pass didn't set it. |
| `##SPECTROMETER FREQUENCY` (or `##.OBSERVE FREQUENCY`) | `parsed.spectrometer_freq` | Drives Hz→ppm when Bruker `$BF1` absent. |
| `$$ Lock substance: X` | `parsed.lock_substance` | |
| `$$ Temperature: X K` | `parsed.temperature`, `parsed.temperature_unit` | Numeric + unit. |

Both enhancers share `_convertHzToPpm(parsed, freq, label)`
so the conversion contract is identical and only ever runs
once.

## Vendor detection — `detectVendor` (H2.5)

`window.scienceNmrVendor.detectVendor(parsed)` returns a
single tag — `'bruker' | 'magritek' | 'mestrenova' |
'unknown'` — by consulting the fields above in priority
order:

1. `parsed.vendor_origin` (Magritek — authoritative).
2. `parsed.bf1` (Bruker — authoritative).
3. `parsed.vendor_hint` (CSV-level signal, lower priority).

The `vendor_hint` is populated by `nmr_csv.js` when it
recognises a vendor name in the comment header of a CSV
export. Detection trusts explicit-header signals over hints
so a file that advertises `##ORIGIN= Magritek` and also
contains the substring "topspin" elsewhere still resolves to
`magritek`.

## Fixtures

| File | Vendor | Layout |
|---|---|---|
| `tests/fixtures/nmr_sample.jdx` | Generic openMiura | `(XY..XY)` |
| `tests/fixtures/nmr_asdf_synthetic.jdx` | Generic + ASDF | `(X++(Y..Y))` with SQZ/DIF/DUP |
| `tests/fixtures/nmr_mestrenova.csv` | MestreNova | CSV, comma-separated |
| `tests/fixtures/nmr_topspin_xy.txt` | Bruker (CSV form) | XY ASCII, tab-separated |
| `tests/fixtures/nmr_bruker_topspin.jdx` | Bruker | JCAMP with `##$BF1` / `##$NUC1` |
| `tests/fixtures/nmr_magritek_spinsolve.jdx` | Magritek | JCAMP with `##ORIGIN= Magritek Spinsolve` |

All fixtures share the same nominal 1H spectrum (peak at
5.0 ppm, Y = 95) so a cross-vendor smoke test can pin the
peak position independent of the encoding.

## Adding a new vendor

1. **Headers**: identify the vendor's authoritative
   advertisement (an `##ORIGIN`, a private namespace like
   `##$`, or a CSV comment prefix).
2. **Enhancer**: add a `_vendorEnhance(parsed, headers,
   allLines)` function in `nmr.js`, after the existing ones.
   Read the headers / comments, populate new `parsed` fields,
   reuse `_convertHzToPpm` if you need Hz→ppm.
3. **Detector**: add a branch to `detectVendor` and a label
   to `vendorLabel`. Preserve priority — explicit headers
   first, hints last.
4. **Fixture + tests**: add a synthetic fixture under
   `tests/fixtures/` and a `test_nmr_<vendor>.py` that pins
   the JS module surface and the fixture's numerical content.
   Reuse the peak position (5.0 ppm, Y = 95) so the smoke
   test in `test_nmr_vendor.py` stays valid.
