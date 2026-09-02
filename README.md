Code to replay data from the pouring dataset. Mocap, scale, and gaze streams are automatically synchronized during playback.

The visualization includes:
  - 3D mocap scene
  - Eye-tracking video (optional)
  - Scale data plot
  - Playback controls

![Pouring playback demo](readme_assets/pouring_raw_data_demo.gif)

# Installation

This project uses `uv` to install and run.

```bash
git clone https://github.com/RothkopfLab/pouring_data_playback.git
cd pouring_data_playback
uv sync
```

---

# Usage

## Download the dataset

Link to full dataset will be added soon. An example recording is placed in the `example_data/` folder.
### Dataset Structure

The recorded data is organized into two main directories:

```
pouring_dataset/
├── data/
└── projects/
```

- `data/`  
  Contains **mocap**, **scale**, and metadata (including references to Tobii recordings).

- `projects/`  
  Contains **Tobii Pro Glasses 2 recordings**, following the original Tobii directory structure.

---

## Playback

Use the following command to replay a recording:

```bash
uv run python main.py \
  --dataset_path example_data/ \
  --mocap_only 0 \
  --rec_time_stamp 02062025092559
```

---

## Arguments

- `--dataset_path`  
  Path to the root dataset directory (`pouring_dataset`)

- `--rec_time_stamp`  
  Timestamp of the recording to replay  
  Format: `ddmmyyyyhhmmss`  
  If not provided, the latest recording is used

- `--mocap_only`  
  - `0` → display mocap + Tobii RGB video  
  - `1` → display mocap only  
  Default: `0`

- `--scene_json`  
  Path to a custom scene json file (optional)  
  If not provided, the default scene configuration is used from object_models folder

---

## Citation

If you use the code or data presented here, please cite:

```bibtex
@article{midlagajni2026pouring,
  title={How to pour a cup of coffee},
  author={Midlagajni, Niteesh and Fleming, Roland W. and Rothkopf, Constantin A.},
  journal={bioRxiv},
  year={2026},
  doi={10.64898/2026.08.26.746627},
  url={https://www.biorxiv.org/content/10.64898/2026.08.26.746627v1}
}
```