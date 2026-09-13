from __future__ import annotations

from pathlib import Path
import os
import sys

from google.cloud import storage


REPO_DIR = Path(__file__).resolve().parent

LOCAL_STATE = (
    REPO_DIR
    / "runtime"
    / "paper_state.json"
)

GCS_OBJECT = (
    "fix17/paper_trader/"
    "paper_state.json"
)


def get_bucket():

    bucket_name = os.environ.get(
        "GCS_BUCKET",
        "",
    ).strip()

    if not bucket_name:
        raise RuntimeError(
            "GCS_BUCKET が設定されていません"
        )

    client = storage.Client()

    return client.bucket(
        bucket_name
    )


def restore():

    bucket = get_bucket()

    blob = bucket.blob(
        GCS_OBJECT
    )

    LOCAL_STATE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not blob.exists():

        print(
            "STATE_RESTORE: FIRST_RUN"
        )

        return

    blob.download_to_filename(
        str(LOCAL_STATE)
    )

    print(
        "STATE_RESTORE: PASS"
    )


def save():

    if not LOCAL_STATE.exists():
        raise RuntimeError(
            "paper_state.json が生成されていません"
        )

    bucket = get_bucket()

    blob = bucket.blob(
        GCS_OBJECT
    )

    blob.upload_from_filename(
        str(LOCAL_STATE),
        content_type="application/json",
    )

    print(
        "STATE_SAVE: PASS"
    )


def main():

    if len(sys.argv) != 2:
        raise RuntimeError(
            "restore または save を指定"
        )

    mode = sys.argv[1].strip().lower()

    if mode == "restore":
        restore()
        return

    if mode == "save":
        save()
        return

    raise RuntimeError(
        f"不明mode: {mode}"
    )


if __name__ == "__main__":
    main()
