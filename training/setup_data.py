"""Build the RIR and background-audio datasets for wake-word training.

Downloads room impulse responses and a slice of AudioSet background noise/music,
writing everything as 16 kHz 16-bit PCM wav (the format `train.py`'s augmentation
expects). Uses huggingface_hub + soundfile directly — no `datasets`/`pyarrow`
version juggling.

Idempotent — skips any output directory that already has files. Tune background
volume with --audioset-shards (500 clips each; more = more robust, slower).
"""

from __future__ import annotations

import argparse
import io
import shutil
from pathlib import Path

import librosa
import numpy as np
import pyarrow.parquet as pq
import soundfile as sf
from huggingface_hub import hf_hub_download, snapshot_download
from tqdm import tqdm

DATA = Path("training/data")
SR = 16000


def _has_files(d: Path) -> bool:
    return d.exists() and any(d.iterdir())


def _write_wav(path: Path, audio: np.ndarray) -> None:
    sf.write(path, (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16), SR, subtype="PCM_16")


def build_rirs() -> None:
    out = DATA / "mit_rirs"
    if _has_files(out):
        print(f"  skip mit_rirs (already populated: {out})")
        return
    out.mkdir(parents=True, exist_ok=True)
    # The repo ships the survey pre-resampled to 16 kHz under 16khz/.
    snap = snapshot_download(
        "davidscripka/MIT_environmental_impulse_responses",
        repo_type="dataset",
        allow_patterns=["16khz/*.wav"],
    )
    wavs = list(Path(snap, "16khz").glob("*.wav"))
    for w in tqdm(wavs, desc="mit_rirs"):
        shutil.copyfile(w, out / w.name)


def build_audioset(n_shards: int) -> None:
    out = DATA / "audioset_16k"
    if _has_files(out):
        print(f"  skip audioset_16k (already populated: {out})")
        return
    out.mkdir(parents=True, exist_ok=True)
    for i in range(n_shards):
        shard = hf_hub_download(
            "agkphysics/AudioSet", f"data/bal_train/{i:02d}.parquet", repo_type="dataset"
        )
        tbl = pq.read_table(shard, columns=["video_id", "audio"])
        ids = tbl.column("video_id").to_pylist()
        audio = tbl.column("audio").to_pylist()  # list of {bytes, path}
        for vid, a in tqdm(list(zip(ids, audio)), desc=f"audioset shard {i:02d}"):
            data, sr = sf.read(io.BytesIO(a["bytes"]), dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)  # to mono
            if sr != SR:
                data = librosa.resample(data, orig_sr=sr, target_sr=SR)
            _write_wav(out / f"{vid}.wav", data)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audioset-shards", type=int, default=2,
                    help="number of AudioSet bal_train parquet shards (500 clips each)")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    build_rirs()
    build_audioset(args.audioset_shards)
    print("Background datasets ready under", DATA)
