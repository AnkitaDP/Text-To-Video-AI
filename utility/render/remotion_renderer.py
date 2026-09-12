import os
import json
import shutil
import subprocess
import hashlib
from urllib.parse import urlparse

import requests


def find_command(*names):
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def download_remote_video(
    url,
    destination,
    timeout=(30, 180),
    max_retries=3,
):
    """
    Download a remote video to a local file.

    Args:
        url (str): Remote video URL.
        destination (str): Local destination path.
        timeout (tuple): (connect timeout, read timeout).
        max_retries (int): Number of attempts.

    Returns:
        str: Local destination path.
    """

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "video/mp4,video/*;q=0.9,*/*;q=0.8",
        "Connection": "keep-alive",
    }

    last_error = None

    for attempt in range(1, max_retries + 1):
        temp_destination = f"{destination}.part"

        try:
            print(
                f"[RemotionRenderer] Downloading remote video "
                f"(attempt {attempt}/{max_retries}): {url}"
            )

            with requests.get(
                url,
                headers=headers,
                stream=True,
                timeout=timeout,
                allow_redirects=True,
            ) as response:

                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                content_length = response.headers.get("content-length")

                print(
                    f"[RemotionRenderer] Pexels response: "
                    f"{response.status_code}, "
                    f"Content-Type: {content_type}, "
                    f"Content-Length: {content_length}"
                )

                if "video" not in content_type.lower() and not url.lower().endswith(
                    ".mp4"
                ):
                    raise RuntimeError(
                        f"Unexpected response type from video URL: {content_type}"
                    )

                os.makedirs(os.path.dirname(destination), exist_ok=True)

                downloaded_bytes = 0

                with open(temp_destination, "wb") as output_file:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue

                        output_file.write(chunk)
                        downloaded_bytes += len(chunk)

                if downloaded_bytes == 0:
                    raise RuntimeError("Downloaded video file is empty.")

                os.replace(temp_destination, destination)

                print(
                    f"[RemotionRenderer] Download complete: "
                    f"{destination} ({downloaded_bytes / (1024 * 1024):.2f} MB)"
                )

                return destination

        except Exception as exc:
            last_error = exc

            print(
                f"[RemotionRenderer] Download attempt {attempt} failed: {exc}"
            )

            try:
                if os.path.exists(temp_destination):
                    os.remove(temp_destination)
            except OSError:
                pass

            if attempt < max_retries:
                print("[RemotionRenderer] Retrying download...")

    raise RuntimeError(
        f"Failed to download remote video after {max_retries} attempts: {url}"
    ) from last_error


def make_safe_video_filename(url, index):
    """
    Creates a deterministic local filename for a remote video.
    """

    parsed = urlparse(url)

    original_name = os.path.basename(parsed.path)

    if original_name:
        extension = os.path.splitext(original_name)[1].lower()
    else:
        extension = ".mp4"

    if not extension:
        extension = ".mp4"

    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    return f"broll_{index}_{url_hash}{extension}"


def render_with_remotion(
    audio_file_path,
    timed_captions,
    background_video_data,
    background_music_path=None,
):
    """
    Renders video using React / Remotion composition.

    Args:
        audio_file_path (str):
            Path to voiceover narration audio.

        timed_captions (list):
            Whisper timed captions list in format:
            [((start, end), word), ...]

        background_video_data (list):
            B-roll segments in format:
            [[(start, end), video_url], ...]

        background_music_path (str, optional):
            Path to background music track.

    Returns:
        str:
            Path to the compiled video output file.
    """

    # ------------------------------------------------------------------
    # 1. Resolve workspace directories
    # ------------------------------------------------------------------

    utility_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    workspace_dir = os.path.dirname(utility_dir)
    composer_dir = os.path.join(workspace_dir, "remotion-composer")

    if not os.path.exists(composer_dir):
        raise FileNotFoundError(
            f"Remotion composer directory not found at: {composer_dir}"
        )

    # ------------------------------------------------------------------
    # 2. Check Node.js / npm / npx
    # ------------------------------------------------------------------

    node_cmd = find_command("node", "node.exe")

    if not node_cmd:
        raise RuntimeError(
            "Node.js is required to render via Remotion, "
            "but was not found on PATH."
        )

    npm_cmd = find_command("npm.cmd", "npm", "npm.exe")
    npx_cmd = find_command("npx.cmd", "npx", "npx.exe")

    if not npm_cmd or not npx_cmd:
        raise RuntimeError(
            "npm and npx are required but were not found on PATH."
        )

    # ------------------------------------------------------------------
    # 3. Ensure npm packages are installed
    # ------------------------------------------------------------------

    node_modules_dir = os.path.join(composer_dir, "node_modules")

    if not os.path.exists(node_modules_dir):
        print(
            "[RemotionRenderer] Installing npm dependencies "
            "in remotion-composer..."
        )

        subprocess.run(
            [npm_cmd, "install"],
            cwd=composer_dir,
            check=True,
        )

    # ------------------------------------------------------------------
    # 4. Prepare public directories
    # ------------------------------------------------------------------

    public_dir = os.path.join(composer_dir, "public")
    os.makedirs(public_dir, exist_ok=True)

    broll_dir = os.path.join(public_dir, "broll_assets")
    os.makedirs(broll_dir, exist_ok=True)

    def clear_broll_directory():
        """
        Remove previously downloaded B-roll files.
        """

        if not os.path.exists(broll_dir):
            return

        for filename in os.listdir(broll_dir):
            file_path = os.path.join(broll_dir, filename)

            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except OSError as exc:
                print(
                    f"[RemotionRenderer] Warning: "
                    f"Could not remove old B-roll asset {file_path}: {exc}"
                )

    clear_broll_directory()

    # ------------------------------------------------------------------
    # 5. Resolve local/remote assets
    # ------------------------------------------------------------------

    def prepare_local_file(src_path, asset_name=None):
        """
        Copies local files into Remotion's public directory.

        Remote HTTP/HTTPS files are downloaded into public/broll_assets
        so Remotion never has to fetch them during rendering.
        """

        if not src_path:
            return None

        # --------------------------------------------------------------
        # Remote URL
        # --------------------------------------------------------------

        if src_path.startswith("http://") or src_path.startswith("https://"):

            if not asset_name:
                asset_name = make_safe_video_filename(
                    src_path,
                    0,
                )

            destination = os.path.join(
                broll_dir,
                asset_name,
            )

            # Download only when not already available.
            if os.path.exists(destination) and os.path.getsize(destination) > 0:
                print(
                    f"[RemotionRenderer] Using existing downloaded asset: "
                    f"{destination}"
                )
            else:
                download_remote_video(
                    src_path,
                    destination,
                )

            # staticFile() expects a path relative to public/
            return os.path.join(
                "broll_assets",
                asset_name,
            ).replace("\\", "/")

        # --------------------------------------------------------------
        # Local file
        # --------------------------------------------------------------

        if os.path.exists(src_path):

            basename = os.path.basename(src_path)
            destination = os.path.join(
                public_dir,
                basename,
            )

            if (
                not os.path.exists(destination)
                or os.path.abspath(src_path) != os.path.abspath(destination)
            ):
                print(
                    f"[RemotionRenderer] Copying local asset to public folder: "
                    f"{src_path} -> {destination}"
                )

                shutil.copy2(
                    src_path,
                    destination,
                )

            return basename

        # --------------------------------------------------------------
        # Unknown path
        # --------------------------------------------------------------

        return src_path

    # ------------------------------------------------------------------
    # 6. Map timed captions to Remotion WordCaption schema
    # ------------------------------------------------------------------

    captions_list = []

    if timed_captions:
        for (t1, t2), word in timed_captions:
            captions_list.append(
                {
                    "word": word,
                    "startMs": int(t1 * 1000),
                    "endMs": int(t2 * 1000),
                }
            )

    # ------------------------------------------------------------------
    # 7. Download B-roll videos BEFORE starting Remotion
    # ------------------------------------------------------------------

    cuts_list = []

    for i, ((t1, t2), source) in enumerate(background_video_data):

        if not source:
            print(
                f"[RemotionRenderer] Warning: Empty B-roll source "
                f"for clip {i}. Skipping."
            )
            continue

        print(
            f"[RemotionRenderer] Preparing B-roll clip {i + 1}/"
            f"{len(background_video_data)}"
        )

        if source.startswith("http://") or source.startswith("https://"):
            asset_filename = make_safe_video_filename(
                source,
                i,
            )

            resolved_source = prepare_local_file(
                source,
                asset_filename,
            )
        else:
            resolved_source = prepare_local_file(
                source,
            )

        cuts_list.append(
            {
                "id": f"clip_{i}",
                "source": resolved_source,
                "in_seconds": float(t1),
                "out_seconds": float(t2),
                "source_in_seconds": 0.0,
            }
        )

    # ------------------------------------------------------------------
    # 8. Prepare narration audio
    # ------------------------------------------------------------------

    resolved_audio = prepare_local_file(
        audio_file_path,
        "audio_tts.wav",
    )

    audio_config = {
        "narration": {
            "src": resolved_audio,
            "volume": 1.0,
        }
    }

    # ------------------------------------------------------------------
    # 9. Prepare optional background music
    # ------------------------------------------------------------------

    if background_music_path:

        resolved_music = prepare_local_file(
            background_music_path,
            "background_music.mp3",
        )

        if resolved_music:
            audio_config["music"] = {
                "src": resolved_music,
                "volume": 0.12,
                "fadeInSeconds": 2.0,
                "fadeOutSeconds": 3.0,
                "offsetSeconds": 0.0,
                "loop": True,
            }

    # ------------------------------------------------------------------
    # 10. Build Remotion props
    # ------------------------------------------------------------------

    props = {
        "cuts": cuts_list,
        "captions": captions_list,
        "audio": audio_config,
        "theme": os.getenv(
            "REMOTION_THEME",
            "flat-motion-graphics",
        ),
    }

    # ------------------------------------------------------------------
    # 11. Write props.json
    # ------------------------------------------------------------------

    props_file_path = os.path.join(
        public_dir,
        "props.json",
    )

    print(
        f"[RemotionRenderer] Writing composition props to "
        f"{props_file_path}..."
    )

    with open(
        props_file_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            props,
            f,
            indent=2,
        )

    # ------------------------------------------------------------------
    # 12. Prepare output directory
    # ------------------------------------------------------------------

    out_dir = os.path.join(
        composer_dir,
        "out",
    )

    os.makedirs(
        out_dir,
        exist_ok=True,
    )

    composer_output_path = os.path.join(
        out_dir,
        "video.mp4",
    )

    # Remove previous render
    if os.path.exists(composer_output_path):
        try:
            os.remove(composer_output_path)
        except OSError as exc:
            print(
                f"[RemotionRenderer] Warning: Could not remove old render: "
                f"{exc}"
            )

    # ------------------------------------------------------------------
    # 13. Render with Remotion
    # ------------------------------------------------------------------

    print(
        "[RemotionRenderer] All B-roll videos are local. "
        "Starting Remotion render..."
    )

    cmd = [
        npx_cmd,
        "remotion",
        "render",
        "src/index.tsx",
        "Explainer",
        composer_output_path,
        "--props",
        "public/props.json",
        "--codec",
        "h264",
    ]

    try:
        subprocess.run(
            cmd,
            cwd=composer_dir,
            check=True,
        )

    finally:
        # --------------------------------------------------------------
        # Cleanup temporary downloaded B-roll files
        # --------------------------------------------------------------

        if os.path.exists(broll_dir):

            for filename in os.listdir(broll_dir):
                file_path = os.path.join(
                    broll_dir,
                    filename,
                )

                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                except OSError as exc:
                    print(
                        f"[RemotionRenderer] Warning: "
                        f"Could not clean up {file_path}: {exc}"
                    )

    # ------------------------------------------------------------------
    # 14. Copy final render back to project root
    # ------------------------------------------------------------------

    final_output_path = os.path.join(
        workspace_dir,
        "rendered_video.mp4",
    )

    if os.path.exists(composer_output_path):

        print(
            f"[RemotionRenderer] Copying rendered video to: "
            f"{final_output_path}"
        )

        shutil.copy2(
            composer_output_path,
            final_output_path,
        )

        return final_output_path

    raise RuntimeError(
        "Remotion render finished, "
        f"but output file was not found at: {composer_output_path}"
    )
