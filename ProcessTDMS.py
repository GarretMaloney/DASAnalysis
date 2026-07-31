"""
ProcessTDMS.py
==============
Reads raw TDMS files, applies ADC scaling, decimates, and concatenates
into a single .npz file for use with AnalyzeStrainSaveFigs.py.
Run once per dataset. No plots are generated here.
"""

import os
import glob
import numpy as np
from scipy.signal import decimate
from nptdms import TdmsFile

# ============================================================
# CONFIGURATION — edit these for each dataset
# ============================================================
tdms_directory   = r"D:\Garret's Experiments\1x Strain Gradient\FLUTe 10PSI"
output_directory = os.path.join(tdms_directory, 'processed')
output_filename  = None   # auto-named from TDMS file (everything before first '_')

decimation_factor = 10    # downsample factor (r)
adc_scalar        = 1 / 8192
nm_conversion     = 116   # radians/sample -> nm/sample scalar
# ============================================================

os.makedirs(output_directory, exist_ok=True)

tdms_files = sorted(glob.glob(os.path.join(tdms_directory, '*.tdms')))
if not tdms_files:
    raise FileNotFoundError(f"No .tdms files found in {tdms_directory}")

fs_f         = None
spatial_samp = None
spatial_res  = None

temp_dir = os.path.join(output_directory, '_temp_chunks')
os.makedirs(temp_dir, exist_ok=True)
chunk_paths = []

for i, tdms_path in enumerate(tdms_files, 1):
    print(f"Processing file {i}/{len(tdms_files)}: {os.path.basename(tdms_path)}")
    tdms     = TdmsFile.read(tdms_path)
    group    = tdms.groups()[0]
    channels = group.channels()

    data_matrix = np.array([ch.data for ch in channels], dtype=np.float32).T

    if fs_f is None:
        fs_f         = float(tdms.properties.get('SamplingFrequency[Hz]', 1000.0))
        spatial_samp = float(tdms.properties.get('SpatialResolution[m]', 0.25))
        spatial_res  = float(tdms.properties.get('GaugeLength', 10.0))
        print(f"  fs_f         = {fs_f} Hz")
        print(f"  spatial_samp = {spatial_samp} m")
        print(f"  spatial_res  = {spatial_res} m")

    # Scale in-place to avoid extra temp arrays
    data_matrix *= adc_scalar
    data_matrix *= nm_conversion
    data_matrix *= fs_f

    print(f"  Decimating {data_matrix.shape[1]} channels by factor {decimation_factor}...")
    n_samples_dec = len(decimate(data_matrix[:, 0], decimation_factor, ftype='iir'))
    decmat = np.empty((n_samples_dec, data_matrix.shape[1]), dtype=np.float32)
    for n in range(data_matrix.shape[1]):
        decmat[:, n] = decimate(data_matrix[:, n], decimation_factor, ftype='iir')

    chunk_path = os.path.join(temp_dir, f'chunk_{i:04d}.npy')
    np.save(chunk_path, decmat)
    chunk_paths.append(chunk_path)
    print(f"  Done. Decimated shape: {decmat.shape}")

    del data_matrix, decmat, tdms

# ============================================================
# CONCATENATE — write directly to memory-mapped file on disk
# to avoid allocating the full array in RAM
# ============================================================
total_samples = sum(np.load(p, mmap_mode='r').shape[0] for p in chunk_paths)
n_channels    = np.load(chunk_paths[0], mmap_mode='r').shape[1]
print(f"\nConcatenating {len(chunk_paths)} chunks → ({total_samples}, {n_channels}) float32")

mmap_path = os.path.join(output_directory, '_decdata_mmap.npy')
decdata   = np.lib.format.open_memmap(mmap_path, mode='w+',
                                       dtype=np.float32,
                                       shape=(total_samples, n_channels))
row = 0
for p in chunk_paths:
    arr = np.load(p)
    decdata[row:row + arr.shape[0], :] = arr
    row += arr.shape[0]
    del arr
    os.remove(p)
os.rmdir(temp_dir)

fs_d = fs_f / decimation_factor
print(f"Concatenated shape: {decdata.shape}  ({decdata.shape[0]/fs_d:.1f} seconds)")

# ============================================================
# SAVE — streams from mmap into .npz without full RAM load
# ============================================================
base_name       = os.path.basename(tdms_files[0])   # e.g. 1hz7v_UTC_20260302.tdms
short_name      = base_name.split('_')[0]            # e.g. 1hz7v
output_filename = short_name + '.npz'

out_path = os.path.join(output_directory, output_filename)
np.savez(out_path,
         decdata      = decdata,
         fs_d         = np.float32(fs_d),
         fs_f         = np.float32(fs_f),
         spatial_samp = np.float32(spatial_samp),
         spatial_res  = np.float32(spatial_res))

decdata.flush()
del decdata
os.remove(mmap_path)

print(f"\nSaved: {out_path}")
print("Done.")