# DAS Strain Transfer Analysis

*Scripts for processing and analyzing distributed acoustic sensing (DAS) data from strain-coupling experiments.*

This repository contains a two-step workflow for converting raw OptaSense TDMS recordings into strain-transfer figures and summary metrics. `ProcessTDMS.py` turns a folder of TDMS files into a single processed array. `AnalyzeStrainSaveFigs.py` loads that array, computes displacement and peak-to-peak amplitudes by cable section, and writes plots plus an Excel log for cross-experiment comparison.

## Workflow

```text
raw *.tdms
      │
      ▼
ProcessTDMS.py          →  processed/*.npz  (decimated strain-rate array + metadata)
      │
      ▼
AnalyzeStrainSaveFigs.py →  figures/*.png  +  StrainTransferResults.xlsx
```

Edit the **CONFIGURATION** block at the top of each script before a run. Paths, section channels, frequency, and bandpass settings are all set there.

## ProcessTDMS.py

Reads every `.tdms` file in a directory, scales the ADC counts to strain rate, decimates in time, and concatenates the results into one `.npz` under a `processed` folder next to the TDMS data.

**What it does:**
- Loads TDMS channel data with `nptdms`
- Applies ADC scaling, nm conversion, and sampling-rate scaling
- Decimates each channel (default factor 10) to reduce file size and later analysis cost
- Writes chunks to disk and concatenates via memory-mapped I/O so overnight datasets do not need to fit fully in RAM
- Saves `decdata`, `fs_d`, `fs_f`, `spatial_samp`, and `spatial_res` in the output `.npz`

Run once per dataset. No figures are produced here.

## AnalyzeStrainSaveFigs.py

Loads the processed `.npz` (or `decdata.npy` + `metadata.npz` if present) and runs the strain-transfer analysis. Section midpoints are defined in a `sections` dictionary; each section measurement averages `ch_avg` channels centered on that midpoint. The number of sections is dynamic.

**Figures written alongside the experiment folder:**
1. Strain-rate waterfall with section windows
2. Bandpass-filtered strain waterfall
3. FFT amplitude spectra (displacement), one subplot per section
3b. FFT spectra of strain rate
4. Mean displacement time series (unfiltered and bandpass)
5. Peak envelopes and strain-transfer ratios vs the reference section
6. Displacement amplitude profile along the fiber

**Metrics:** peak-to-peak amplitudes (unfiltered and bandpass) for the reference and each test cable, plus transfer ratios relative to the reference. Results are appended to a shared Excel workbook keyed by drive frequency and voltage for comparing runs.

Large arrays stay float32 where possible; waterfalls and some plots are downsampled for display so long acquisitions do not OOM.

## Dependencies

```text
numpy
scipy
matplotlib
nptdms
openpyxl
```

## Configuration notes

- Point `ProcessTDMS.py` at the folder containing the raw `.tdms` files.
- Point `AnalyzeStrainSaveFigs.py` at the resulting `processed` directory and set `excel_path` for the results workbook.
- Set `Freq` explicitly or leave as `None` to auto-detect from the reference section spectrum.
- Set `bp_low` / `bp_high` explicitly or leave as `None` to derive a band around `Freq`.
- Adjust `sections`, `ref_channel`, and `inner_channels` to match the cable layout for that experiment.
