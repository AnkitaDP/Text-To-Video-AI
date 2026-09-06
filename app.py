import os
import asyncio
import argparse
import requests
import imageio_ffmpeg

ffmpeg_exe_src = imageio_ffmpeg.get_ffmpeg_exe()
bin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
os.makedirs(bin_dir, exist_ok=True)
ffmpeg_exe_dest = os.path.join(bin_dir, "ffmpeg.exe")

if not os.path.exists(ffmpeg_exe_dest):
    print(f"[Pipeline] Copying bundled ffmpeg to local bin: {ffmpeg_exe_src} -> {ffmpeg_exe_dest}")
    import shutil
    shutil.copy2(ffmpeg_exe_src, ffmpeg_exe_dest)

if bin_dir not in os.environ["PATH"]:
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]
from utility.script.script_generator import generate_script
from utility.audio.audio_generator import generate_audio
from utility.captions.timed_captions_generator import generate_timed_captions
from utility.video.background_video_generator import generate_video_url
from utility.render.render_engine import get_output_media
from utility.video.video_search_query_generator import getVideoSearchQueriesTimed, merge_empty_intervals
from utility.config import get_config
from utility.pipeline_manager import PipelineManager

def download_file(url, filename):
    print(f"[Pipeline] Downloading: {url} -> {filename}")
    with open(filename, 'wb') as f:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        f.write(response.content)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a video from a topic.")
    parser.add_argument("topic", type=str, help="The topic for the video")
    args = parser.parse_args()

    config = get_config()
    orientation_landscape = config.get_video_orientation()
    aspect_ratio = "16:9" if orientation_landscape else "9:16"

    # Initialize PipelineManager
    manager = PipelineManager(args.topic)
    topic = manager.get_data("topic")

    # 1. Generate Script
    if manager.get_stage() == "1_script":
        print("\n--- STAGE 1: Generating Script ---")
        script = generate_script(topic)
        print(f"Generated Script: {script}")
        manager.update_data("script", script)
        manager.set_stage("2_voiceover")

    # 2. Generate Voiceover
    if manager.get_stage() == "2_voiceover":
        print("\n--- STAGE 2: Generating Voiceover ---")
        script = manager.get_data("script")
        voiceover_filename = "audio_tts.wav"
        asyncio.run(generate_audio(script, voiceover_filename))
        print(f"Generated voiceover saved to: {voiceover_filename}")
        manager.update_data("voiceover_path", voiceover_filename)
        manager.set_stage("3_timed_captions")

    # 3. Generate Timed Captions
    if manager.get_stage() == "3_timed_captions":
        print("\n--- STAGE 3: Generating Timed Captions ---")
        voiceover_filename = manager.get_data("voiceover_path")
        timed_captions = generate_timed_captions(voiceover_filename)
        print(f"Generated timed captions: {timed_captions}")
        manager.update_data("timed_captions", timed_captions)
        manager.set_stage("4_background_music")

    # 4. Generate Background Music
    if manager.get_stage() == "4_background_music":
        print("\n--- STAGE 4: Generating Background Music ---")
        print("Skipping Suno background music generation.")
        manager.set_stage("5_ai_video_broll")

    # 5. Generate Timed B-roll Videos
    if manager.get_stage() == "5_ai_video_broll":
        print("\n--- STAGE 5: Sourcing Timed B-Roll Videos ---")
        script = manager.get_data("script")
        timed_captions = manager.get_data("timed_captions")
        search_terms = getVideoSearchQueriesTimed(script, timed_captions)
        background_video_urls = manager.get_data("background_video_urls") or []
        
        print("Using stock Pexels API for B-roll...")
        background_video_urls = generate_video_url(search_terms, "pexel", orientation_landscape=orientation_landscape)
        manager.update_data("background_video_urls", background_video_urls)
        manager.set_stage("6_render")

    # 6. Render final composite video
    if manager.get_stage() == "6_render":
        print("\n--- STAGE 6: Rendering Final Video ---")
        voiceover_path = manager.get_data("voiceover_path")
        timed_captions = manager.get_data("timed_captions")
        background_video_urls = manager.get_data("background_video_urls")
        background_music_path = manager.get_data("background_music_path")

        # Clean/merge intervals
        background_video_urls = merge_empty_intervals(background_video_urls)

        if background_video_urls:
            print("Compiling media files...")
            video_output = get_output_media(
                audio_file_path=voiceover_path,
                timed_captions=timed_captions,
                background_video_data=background_video_urls,
                video_server="pexel", # Just standard downloader
                background_music_path=background_music_path
            )
            print(f"\nSUCCESS! Final video saved as '{video_output}'")
            manager.update_data("video_path", video_output)
            # Finish pipeline
            manager.set_stage("completed")
        else:
            print("Error: No background video clips found. Cannot render.")

    if manager.get_stage() == "completed":
        print("\nPipeline execution complete! Resetting checkpoint...")
        # Reset checkpoint for future runs
        if os.path.exists("pipeline_checkpoint.json"):
            try:
                os.remove("pipeline_checkpoint.json")
            except Exception as e:
                print(f"Error cleaning up checkpoint: {e}")
