"""
AnalyzeStrain.py
================
Loads processed .npz file from ProcessTDMS.py and performs:
  - Strain rate / strain waterfall plots
  - FFT amplitude spectrum
  - Mean displacement inside vs outside casing
  - Peak envelope analysis and strain transfer ratio (unfiltered + bandpass)

Exploratory mode: plots are shown interactively and no files are written.
Excel export is disabled in this residual-analysis variant.

Edit the CONFIGURATION block for each run. No processing is redone.
"""

import os
import re
import glob
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from scipy.signal import detrend, butter, sosfiltfilt, find_peaks
from scipy.interpolate import interp1d

# ============================================================
# CONFIGURATION — edit these between runs
# ============================================================
processed_directory = r'D:\Single Fiber Experiments\0.001hz\7V\processed'

# Excel path retained for later re-enable (currently unused)
excel_path = r'D:\Single Fiber Experiments\StrainTransferResults.xlsx'

# Frequency — set to float to override, None = auto from folder name, then FFT fallback
Freq = None

# Exploratory plotting controls
# keep save_figures=False for look-only runs with no file output.
show_plots = True
save_figures = False

# Set to True only for headless runs where GUI plotting is unavailable.
force_agg_backend = False
if force_agg_backend:
    matplotlib.use('Agg')

# Channel ranges for inside/outside comparison
outside_range = range(95,  105)
inside_range  = range(205, 215)

# Channel subset
ch_start = 1
ch_stop  = 340

spatial_res = 0.25   # m/channel

# Bandpass — None = auto-scale at ±50% of Freq
bp_low   = None
bp_high  = None
bp_order = 2

# Max samples for waterfall plots — downsamples in time only if exceeded
# Keeps memory under control for long records (e.g. 0.001 Hz datasets)
waterfall_max_samples = 50000
# ============================================================


# ============================================================
# UTILITIES
# ============================================================
def cumtrapz(y, dx=1.0, axis=-1):
    y = np.moveaxis(y, axis, -1)
    out = np.cumsum((y[..., 1:] + y[..., :-1]) * 0.5, axis=-1) * dx
    out = np.concatenate([np.zeros((*out.shape[:-1], 1), dtype=out.dtype), out], axis=-1)
    return np.moveaxis(out, -1, axis)

def bandpass(data, fs, lowcut, highcut, order=2):
    nyq = 0.5 * fs
    sos = butter(order, [lowcut / nyq, highcut / nyq], btype='band', output='sos')
    return sosfiltfilt(sos, data, axis=-1)

def nextpow2(n):
    return int(np.ceil(np.log2(max(n, 1))))

def peak_envelope(x, fs, freq_hz):
    tloc     = np.arange(x.size) / fs
    min_dist = max(1, int(round(0.8 * fs / max(freq_hz, 1e-9))))
    p_idx,  _ = find_peaks( x, distance=min_dist)
    tr_idx, _ = find_peaks(-x, distance=min_dist)
    if p_idx.size >= 2:
        upper = interp1d(tloc[p_idx],  x[p_idx],  kind='linear',
                         fill_value='extrapolate', bounds_error=False)(tloc)
    else:
        upper = np.maximum.accumulate(x)
    if tr_idx.size >= 2:
        lower = interp1d(tloc[tr_idx], x[tr_idx], kind='linear',
                         fill_value='extrapolate', bounds_error=False)(tloc)
    else:
        lower = -np.maximum.accumulate(-x)
    return upper, lower, (upper - lower)

def remove_single_tone(x, fs, freq_hz):
    """Least-squares remove one sinusoidal component and DC offset."""
    tloc = np.arange(x.size) / fs
    w = 2.0 * np.pi * freq_hz
    design = np.column_stack([np.sin(w * tloc), np.cos(w * tloc), np.ones_like(tloc)])
    coeff, *_ = np.linalg.lstsq(design, x, rcond=None)
    tone = design @ coeff
    residual = x - tone
    tone_amp = float(np.hypot(coeff[0], coeff[1]))
    return residual, tone, tone_amp

def savefig(fig, figures_dir, name):
    path = os.path.join(figures_dir, name)
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path}")

def parse_hz(s):
    m = re.search(r'(\d+\.?\d*)\s*hz', s.lower())
    return float(m.group(1)) if m else None

def parse_voltage(s):
    m = re.search(r'(\d+\.?\d*)\s*v', s.lower())
    return float(m.group(1)) if m else None


# ============================================================
# SETUP DIRECTORIES
# ============================================================
base_dir    = os.path.dirname(processed_directory.rstrip(os.sep))
figures_dir = os.path.join(base_dir, 'figures')
if save_figures:
    os.makedirs(figures_dir, exist_ok=True)

# Parse freq and voltage from path
path_parts  = processed_directory.replace('\\', '/').split('/')
vol_folder  = path_parts[-2] if path_parts[-1] == 'processed' else path_parts[-1]
freq_folder = path_parts[-3] if path_parts[-1] == 'processed' else path_parts[-2]
freq_val    = parse_hz(freq_folder)
voltage_val = parse_voltage(vol_folder)

# ============================================================
# LOAD DATA
# ============================================================
npz_files = sorted(glob.glob(os.path.join(processed_directory, '*.npz')))
if not npz_files:
    raise FileNotFoundError(f"No .npz files found in {processed_directory}")
npz_file = npz_files[0]
print(f"Loading: {os.path.basename(npz_file)} from {processed_directory}")

npz     = np.load(npz_file)
decdata = npz['decdata'].astype(np.float64)
fs_d    = float(npz['fs_d'])
print(f"  Shape: {decdata.shape}  |  fs_d: {fs_d} Hz  |  Duration: {decdata.shape[0]/fs_d:.1f} s")

# ============================================================
# SETUP
# ============================================================
subdata    = decdata[:, ch_start:ch_stop].T    # [channels x time]
nch        = subdata.shape[0]
L          = subdata.shape[1]
t          = np.arange(L) / fs_d
depth_axis = np.arange(ch_start, ch_stop) * spatial_res

outside_idx = np.array([i - ch_start for i in outside_range if ch_start <= i < ch_start + nch])
inside_idx  = np.array([i - ch_start for i in inside_range  if ch_start <= i < ch_start + nch])

# ============================================================
# FREQUENCY DETECTION
# ============================================================
RateOut_mean = subdata[outside_idx, :].mean(axis=0)
RateOut_mean -= RateOut_mean.mean()
DispOut_raw  = cumtrapz(RateOut_mean, dx=1/fs_d) * 1e-3

NFFT   = 2 ** (max(nextpow2(L + 1) - 1, 1))
f_axis = fs_d / 2 * np.linspace(0, 1, NFFT // 2 + 1)
Amp_detect = 2 * np.abs(np.fft.fft(detrend(DispOut_raw, type='linear'), n=NFFT)[:NFFT//2+1]) / NFFT

min_freq_idx = max(1, int(0.0005 * NFFT / fs_d))
detected_idx = min_freq_idx + int(np.argmax(Amp_detect[min_freq_idx:]))
Freq_auto = float(f_axis[detected_idx])
print(f"  Auto-detected frequency : {Freq_auto:.4f} Hz")

if Freq is not None:
    print(f"  NOTE: manual Freq={Freq:.4f} Hz ignored for residual subtraction")
if freq_val is not None:
    print(f"  NOTE: folder frequency={freq_val:.4f} Hz retained for metadata only")
Freq = Freq_auto

if bp_low  is None:
    bp_low  = max(Freq * 0.5, 0.00001)
if bp_high is None:
    bp_high = min(Freq * 1.5, fs_d / 2 * 0.99)
print(f"  Bandpass: {bp_low:.5f} – {bp_high:.5f} Hz")

# ============================================================
# WATERFALL — downsampled for memory safety
# ============================================================
wf_step = max(1, int(np.ceil(L / waterfall_max_samples)))
wf_data = subdata[:, ::wf_step].astype(np.float32)   # [ch x time_ds]
wf_t    = t[::wf_step]
if wf_step > 1:
    print(f"  Waterfall downsampled by {wf_step}x for plotting ({wf_data.shape[1]} samples)")

wf_filt = bandpass(wf_data.astype(np.float64), fs_d / wf_step, bp_low, bp_high, bp_order)

# ============================================================
# FIGURE 1 — Strain Rate Waterfall
# ============================================================
fig1 = plt.figure(figsize=(12, 6))
plt.imshow(wf_data, aspect='auto', cmap='jet',
           extent=[wf_t[0], wf_t[-1], depth_axis[-1], depth_axis[0]],
           vmin=np.nanpercentile(wf_data, 2),
           vmax=np.nanpercentile(wf_data, 98))
plt.colorbar(label='Strain Rate (nm/sec)')
plt.xlabel('Time (s)'); plt.ylabel('Depth (m)')
plt.title('Strain Rate Waterfall')
plt.tight_layout()
if save_figures:
    savefig(fig1, figures_dir, 'fig1_strain_rate_waterfall.png')
elif not show_plots:
    plt.close(fig1)

# ============================================================
# FIGURE 2 — Filtered Strain Waterfall
# ============================================================
fig2 = plt.figure(figsize=(12, 6))
plt.imshow(wf_filt, aspect='auto', cmap='jet',
           extent=[wf_t[0], wf_t[-1], depth_axis[-1], depth_axis[0]],
           vmin=np.nanpercentile(wf_filt, 2),
           vmax=np.nanpercentile(wf_filt, 98))
plt.colorbar(label='Strain (μm)')
plt.xlabel('Time (s)'); plt.ylabel('Depth (m)')
plt.title(f'Strain Waterfall (Bandpass {bp_low:.5f}–{bp_high:.5f} Hz)')
plt.tight_layout()
if save_figures:
    savefig(fig2, figures_dir, 'fig2_strain_waterfall_filtered.png')
elif not show_plots:
    plt.close(fig2)

# Free waterfall arrays
del wf_data, wf_filt

# ============================================================
# FIGURE 3 — FFT Amplitude Spectrum
# ============================================================
dDispOut_fft     = detrend(DispOut_raw, type='linear')
DispOut_filt_raw = bandpass(DispOut_raw, fs_d, bp_low, bp_high, bp_order)
dDispOut_filt    = detrend(DispOut_filt_raw, type='linear')

Amp_un = 2 * np.abs(np.fft.fft(dDispOut_fft,  n=NFFT)[:NFFT//2+1]) / NFFT
Amp_fi = 2 * np.abs(np.fft.fft(dDispOut_filt, n=NFFT)[:NFFT//2+1]) / NFFT

fmax_show = min(5 * Freq, fs_d / 2)
fmask     = f_axis <= fmax_show
ymax      = max(Amp_un[fmask].max(), Amp_fi[fmask].max()) * 1.1

fig3 = plt.figure(figsize=(7, 4))
plt.plot(f_axis[fmask], Amp_un[fmask], 'b-', lw=1.5, label='Unfiltered')
plt.plot(f_axis[fmask], Amp_fi[fmask], 'r-', lw=1.5, label='Filtered')
plt.axvline(Freq, color='k', linestyle='--', alpha=0.5, label=f'{Freq:.5f} Hz')
plt.xlabel('Frequency (Hz)'); plt.ylabel('Amplitude (μm)')
plt.title('Amplitude Spectrum — Outside Mean Displacement')
plt.xlim([0, fmax_show]); plt.ylim([0, ymax])
plt.legend(); plt.grid(True); plt.tight_layout()
# savefig(fig3, figures_dir, 'fig3_fft_spectrum.png')
if not show_plots:
    plt.close(fig3)

# ============================================================
# FIGURE 4 — Mean Displacement: Unfiltered vs Bandpass
# ============================================================
RateIn_mean  = subdata[inside_idx, :].mean(axis=0)
RateIn_mean -= RateIn_mean.mean()

DispOut = cumtrapz(RateOut_mean, dx=1/fs_d) * 1e-3
DispIn  = cumtrapz(RateIn_mean,  dx=1/fs_d) * 1e-3

DispOut_res, DispOut_tone, out_tone_amp = remove_single_tone(DispOut, fs_d, Freq_auto)
DispIn_res,  DispIn_tone,  in_tone_amp  = remove_single_tone(DispIn,  fs_d, Freq_auto)
print(f"  Removed fitted {Freq_auto:.5f} Hz tone: Out amp={out_tone_amp:.4f} μm, In amp={in_tone_amp:.4f} μm")

DispOut_filt = bandpass(DispOut_res, fs_d, bp_low, bp_high, bp_order)
DispIn_filt  = bandpass(DispIn_res,  fs_d, bp_low, bp_high, bp_order)

fig4, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
axes[0].plot(t, DispOut_res, label='Outside residual')
axes[0].plot(t, DispIn_res, label='Inside residual')
axes[0].set_ylabel('Displacement (μm)')
axes[0].set_title(f'Mean Displacement Residual (tone removed at {Freq_auto:.5f} Hz)')
axes[0].legend(); axes[0].grid(True)
axes[1].plot(t, DispOut_filt, label='Outside')
axes[1].plot(t, DispIn_filt,  label='Inside')
axes[1].set_ylabel('Displacement (μm)'); axes[1].set_xlabel('Time (s)')
axes[1].set_title(f'Residual Bandpass {bp_low:.5f}–{bp_high:.5f} Hz')
axes[1].legend(); axes[1].grid(True)
plt.tight_layout()
# savefig(fig4, figures_dir, 'fig4_mean_displacement.png')
if not show_plots:
    plt.close(fig4)

# ============================================================
# FIGURE 5 — Envelopes: Unfiltered vs Bandpass
# ============================================================
dDispOut = detrend(DispOut_res, type='linear')
dDispIn  = detrend(DispIn_res,  type='linear')

upOut_raw, loOut_raw, ampOut_raw = peak_envelope(dDispOut,     fs_d, Freq)
upIn_raw,  loIn_raw,  ampIn_raw  = peak_envelope(dDispIn,      fs_d, Freq)
upOut_bp,  loOut_bp,  ampOut_bp  = peak_envelope(DispOut_filt, fs_d, Freq)
upIn_bp,   loIn_bp,   ampIn_bp   = peak_envelope(DispIn_filt,  fs_d, Freq)

aOut_raw  = float(np.nanmean(ampOut_raw));  aIn_raw = float(np.nanmean(ampIn_raw))
aOut_bp   = float(np.nanmean(ampOut_bp));   aIn_bp  = float(np.nanmean(ampIn_bp))
ratio_raw = aIn_raw / aOut_raw if aOut_raw > 0 else np.nan
ratio_bp  = aIn_bp  / aOut_bp  if aOut_bp  > 0 else np.nan

fig5, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
axes[0].plot(t, dDispOut,  'b',   label='Outside (detrended)')
axes[0].plot(t, upOut_raw, 'b--', label='Upper Env Out')
axes[0].plot(t, loOut_raw, 'b--')
axes[0].plot(t, dDispIn,   'r',   label='Inside (detrended)')
axes[0].plot(t, upIn_raw,  'r--', label='Upper Env In')
axes[0].plot(t, loIn_raw,  'r--')
axes[0].set_ylabel('Displacement (μm)')
axes[0].set_title(f'Residual (tone removed) — P-P Out: {aOut_raw:.3f} μm | P-P In: {aIn_raw:.3f} μm | Ratio: {ratio_raw:.4f} ({ratio_raw*100:.1f}%)')
axes[0].legend(ncol=2); axes[0].grid(True)
axes[1].plot(t, DispOut_filt, 'b',   label='Outside (bandpass)')
axes[1].plot(t, upOut_bp,     'b--', label='Upper Env Out')
axes[1].plot(t, loOut_bp,     'b--')
axes[1].plot(t, DispIn_filt,  'r',   label='Inside (bandpass)')
axes[1].plot(t, upIn_bp,      'r--', label='Upper Env In')
axes[1].plot(t, loIn_bp,      'r--')
axes[1].set_ylabel('Displacement (μm)'); axes[1].set_xlabel('Seconds')
axes[1].set_title(f'Residual bandpass {bp_low:.5f}–{bp_high:.5f} Hz — P-P Out: {aOut_bp:.3f} μm | P-P In: {aIn_bp:.3f} μm | Ratio: {ratio_bp:.4f} ({ratio_bp*100:.1f}%)')
axes[1].legend(ncol=2); axes[1].grid(True)
plt.tight_layout()
# savefig(fig5, figures_dir, 'fig5_envelopes.png')
if not show_plots:
    plt.close(fig5)

# ============================================================
# SUMMARY
# ============================================================
print("\n========== STRAIN TRANSFER SUMMARY ==========")
print(f"  File                : {os.path.basename(npz_file)}")
print(f"  Figure saving       : {'enabled' if save_figures else 'disabled (exploratory)'}")
print(f"  Plot display        : {'enabled' if show_plots else 'disabled'}")
print(f"  Auto frequency      : {Freq_auto:.5f} Hz")
print(f"  Bandpass            : {bp_low:.5f} – {bp_high:.5f} Hz")
print(f"  Outside channels    : {list(outside_range)}")
print(f"  Inside channels     : {list(inside_range)}")
print(f"  {'Method':<22} {'P-P OUT':>9} {'P-P IN':>9} {'Ratio':>14}")
print(f"  {'-'*56}")
print(f"  {'Residual':<22} {aOut_raw:>7.3f} μm {aIn_raw:>7.3f} μm {ratio_raw:>7.4f} ({ratio_raw*100:.1f}%)")
print(f"  {'Residual Bandpass':<22} {aOut_bp:>7.3f} μm {aIn_bp:>7.3f} μm {ratio_bp:>7.4f} ({ratio_bp*100:.1f}%)")
print("==============================================\n")

# ============================================================
# EXCEL EXPORT (DISABLED FOR EXPLORATORY RUNS)
# ============================================================
print("  Excel logging       : disabled (exploratory)")

# Keep exploratory plots visible at the end of script execution.
if show_plots:
    plt.show()