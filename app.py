import os
import re
import uuid
import zipfile
import shutil
from pathlib import Path
from datetime import datetime

import numpy as np
import pydicom
from pydicom.pixel_data_handlers.util import apply_voi_lut
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, abort


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/dicom_jpg_app"))
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
JOB_INDEX = DATA_DIR / "jobs.json"

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

for folder in [DATA_DIR, UPLOAD_DIR, OUTPUT_DIR]:
    folder.mkdir(parents=True, exist_ok=True)


def load_jobs():
    if JOB_INDEX.exists():
        try:
            return json_load(JOB_INDEX)
        except Exception:
            return []
    return []


def save_jobs(jobs):
    JOB_INDEX.write_text(json_dumps(jobs), encoding="utf-8")


def json_load(path):
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))


def json_dumps(data):
    import json
    return json.dumps(data, ensure_ascii=False, indent=2)


def clean_filename(text, default="Unknown"):
    if text is None:
        return default
    text = str(text).strip()
    text = text.replace("^", "_")
    text = re.sub(r'[\\/*?:"<>|]', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text[:90]
    return text if text else default


def dicom_date(ds):
    for field in ["StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate"]:
        value = getattr(ds, field, None)
        if value:
            value = str(value)
            if len(value) >= 8:
                return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    return "Unknown_Date"


def dicom_time(ds):
    for field in ["StudyTime", "SeriesTime", "AcquisitionTime", "ContentTime"]:
        value = getattr(ds, field, None)
        if value:
            value = str(value).split(".")[0].ljust(6, "0")
            if len(value) >= 6:
                return f"{value[0:2]}-{value[2:4]}-{value[4:6]}"
    return "Unknown_Time"


def normalize_to_uint8(arr):
    arr = arr.astype(np.float32)
    mn = float(np.min(arr))
    mx = float(np.max(arr))
    if mx == mn:
        return np.zeros(arr.shape, dtype=np.uint8)
    arr = (arr - mn) / (mx - mn)
    return (arr * 255).clip(0, 255).astype(np.uint8)


def dicom_to_uint8(ds):
    pixels = ds.pixel_array

    # Multi-frame DICOM: all frames are handled outside when ndim >= 3.
    # Here only one 2D image is expected.
    if pixels.ndim > 2:
        pixels = pixels[0]

    try:
        pixels = apply_voi_lut(pixels, ds)
    except Exception:
        pass

    pixels = pixels.astype(np.float32)

    slope = float(getattr(ds, "RescaleSlope", 1))
    intercept = float(getattr(ds, "RescaleIntercept", 0))
    pixels = pixels * slope + intercept

    image = normalize_to_uint8(pixels)

    if getattr(ds, "PhotometricInterpretation", "") == "MONOCHROME1":
        image = 255 - image

    return image


def save_jpg(image_array, output_path):
    image = Image.fromarray(image_array)
    if image.mode != "L":
        image = image.convert("L")
    image.save(output_path, "JPEG", quality=95, optimize=True)


def convert_one_dicom(dicom_path, output_root):
    ds = pydicom.dcmread(str(dicom_path), force=True)

    if not hasattr(ds, "PixelData"):
        return 0, f"Görüntü verisi yok: {dicom_path.name}"

    date_text = dicom_date(ds)
    time_text = dicom_time(ds)

    patient_name = clean_filename(getattr(ds, "PatientName", "UnknownPatient"), "UnknownPatient")
    study_desc = clean_filename(getattr(ds, "StudyDescription", "Study"), "Study")
    series_desc = clean_filename(getattr(ds, "SeriesDescription", "Series"), "Series")
    series_no = clean_filename(getattr(ds, "SeriesNumber", "0"), "0")
    instance_no = clean_filename(getattr(ds, "InstanceNumber", "0"), "0")

    out_folder = Path(output_root) / date_text / study_desc / f"Seri_{series_no}_{series_desc}"
    out_folder.mkdir(parents=True, exist_ok=True)

    arr = ds.pixel_array

    saved = 0

    # Multi-frame DICOM
    if arr.ndim == 3 and arr.shape[0] > 1:
        for idx in range(arr.shape[0]):
            frame_ds = ds.copy()
            frame_ds.PixelData = arr[idx].tobytes()
            frame_ds.Rows = arr[idx].shape[0]
            frame_ds.Columns = arr[idx].shape[1]

            img = normalize_to_uint8(arr[idx])
            if getattr(ds, "PhotometricInterpretation", "") == "MONOCHROME1":
                img = 255 - img

            jpg_name = (
                f"{date_text}_{time_text}_{patient_name}_"
                f"Ser{series_no}_Img{instance_no}_Frame{idx + 1}.jpg"
            )
            save_jpg(img, out_folder / jpg_name)
            saved += 1
        return saved, None

    img = dicom_to_uint8(ds)
    jpg_name = f"{date_text}_{time_text}_{patient_name}_Ser{series_no}_Img{instance_no}.jpg"
    save_jpg(img, out_folder / jpg_name)
    return 1, None


def safe_extract_zip(zip_path, dest_dir):
    dest_dir = Path(dest_dir).resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            target = (dest_dir / member.filename).resolve()
            if not str(target).startswith(str(dest_dir)):
                raise ValueError("Güvensiz ZIP yolu algılandı.")
        zf.extractall(dest_dir)


def find_files(folder):
    for p in Path(folder).rglob("*"):
        if p.is_file():
            yield p


def make_zip_from_folder(folder, zip_path):
    folder = Path(folder)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in folder.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(folder))


def process_uploads(files):
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    job_upload_dir = UPLOAD_DIR / job_id
    job_output_dir = OUTPUT_DIR / job_id / "jpg"
    job_upload_dir.mkdir(parents=True, exist_ok=True)
    job_output_dir.mkdir(parents=True, exist_ok=True)

    original_names = []
    total_saved = 0
    skipped = []
    errors = []

    for uploaded in files:
        if not uploaded or not uploaded.filename:
            continue

        # Klasör yüklemede tarayıcı dosya adını şu şekilde gönderir:
        # "AnaKlasor/AltKlasor/DICOM001"
        # Bu göreli yolu güvenli şekilde koruyup kaydediyoruz.
        raw_name = uploaded.filename or "upload"

        parts = []
        for part in raw_name.replace("\\", "/").split("/"):
            safe_part = clean_filename(part, "item")
            if safe_part not in ["", ".", ".."]:
                parts.append(safe_part)

        if not parts:
            parts = ["upload"]

        original_name = "/".join(parts)
        original_names.append(original_name)

        saved_path = job_upload_dir.joinpath(*parts)
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        uploaded.save(saved_path)

        if zipfile.is_zipfile(saved_path):
            extract_dir = job_upload_dir / f"unzipped_{saved_path.stem}"
            extract_dir.mkdir(parents=True, exist_ok=True)
            try:
                safe_extract_zip(saved_path, extract_dir)
            except Exception as e:
                errors.append(f"ZIP açılamadı: {original_name} - {e}")

    candidates = list(find_files(job_upload_dir))

    for file_path in candidates:
        try:
            if zipfile.is_zipfile(file_path):
                continue

            # DICOM olup olmadığını hızlı kontrol et
            try:
                ds_head = pydicom.dcmread(str(file_path), stop_before_pixels=True, force=True)
                if not hasattr(ds_head, "SOPClassUID") and not hasattr(ds_head, "StudyDate"):
                    skipped.append(file_path.name)
                    continue
            except Exception:
                skipped.append(file_path.name)
                continue

            count, warn = convert_one_dicom(file_path, job_output_dir)
            total_saved += count
            if warn:
                skipped.append(warn)

        except Exception as e:
            errors.append(f"{file_path.name}: {e}")

    zip_result = OUTPUT_DIR / job_id / "dicom_jpg_sonuclar.zip"
    make_zip_from_folder(job_output_dir, zip_result)

    job = {
        "id": job_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "original_names": original_names,
        "jpg_count": total_saved,
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "zip_path": str(zip_result),
        "output_dir": str(job_output_dir),
        "skipped": skipped[:50],
        "errors": errors[:50],
    }

    jobs = load_jobs()
    jobs.insert(0, job)
    save_jobs(jobs[:100])

    return job


@app.route("/")
def index():
    jobs = load_jobs()
    return render_template("index.html", jobs=jobs, max_upload_mb=MAX_UPLOAD_MB)


@app.route("/upload", methods=["POST"])
def upload():
    uploaded_files = request.files.getlist("files")
    if not uploaded_files:
        flash("Dosya seçilmedi.")
        return redirect(url_for("index"))

    job = process_uploads(uploaded_files)

    if job["jpg_count"] == 0:
        flash("DICOM görüntüsü bulunamadı veya JPG üretilemedi.")
    else:
        flash(f"{job['jpg_count']} adet JPG oluşturuldu.")

    return redirect(url_for("job_detail", job_id=job["id"]))


@app.route("/job/<job_id>")
def job_detail(job_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        abort(404)

    jpg_files = []
    out_dir = Path(job["output_dir"])
    if out_dir.exists():
        for p in out_dir.rglob("*.jpg"):
            jpg_files.append({
                "name": str(p.relative_to(out_dir)),
                "url": url_for("download_single", job_id=job_id, rel_path=str(p.relative_to(out_dir)))
            })

    return render_template("job.html", job=job, jpg_files=jpg_files)


@app.route("/download/<job_id>")
def download_zip(job_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        abort(404)

    zip_path = Path(job["zip_path"])
    if not zip_path.exists():
        abort(404)

    return send_file(zip_path, as_attachment=True, download_name=f"{job_id}_jpg.zip")


@app.route("/download-single/<job_id>/<path:rel_path>")
def download_single(job_id, rel_path):
    jobs = load_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        abort(404)

    out_dir = Path(job["output_dir"]).resolve()
    file_path = (out_dir / rel_path).resolve()

    if not str(file_path).startswith(str(out_dir)) or not file_path.exists():
        abort(404)

    return send_file(file_path, as_attachment=True, download_name=file_path.name)


@app.route("/delete/<job_id>", methods=["POST"])
def delete_job(job_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        abort(404)

    shutil.rmtree(UPLOAD_DIR / job_id, ignore_errors=True)
    shutil.rmtree(OUTPUT_DIR / job_id, ignore_errors=True)

    jobs = [j for j in jobs if j["id"] != job_id]
    save_jobs(jobs)

    flash("Kayıt silindi.")
    return redirect(url_for("index"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
