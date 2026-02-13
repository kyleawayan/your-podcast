"""Voice testing module for comparing TTS providers."""

from pathlib import Path

from pydub import AudioSegment
from rich.console import Console

from your_podcast.podcast.macos_tts import (
    generate_audio_macos,
    get_pause_duration,
    parse_transcript,
)
from your_podcast.podcast.chatterbox_tts import generate_audio_chatterbox
from your_podcast.podcast.google_cloud_tts import generate_audio_google_cloud
from your_podcast.settings import get_settings

console = Console()

TEST_TRANSCRIPT = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "voice_test.txt"
OUTPUT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "test_audio"


def test_macos_voices() -> Path:
    """Generate test audio using macOS TTS."""
    settings = get_settings()
    transcript = TEST_TRANSCRIPT.read_text()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "test_macos.mp3"

    console.print("[bold]Testing macOS TTS...[/bold]")
    generate_audio_macos(
        transcript=transcript,
        voice_1=settings.macos_voice_1,
        voice_2=settings.macos_voice_2,
        output_path=str(output_path),
    )
    return output_path


def test_elevenlabs_voices() -> Path | None:
    """Generate test audio using ElevenLabs TTS."""
    settings = get_settings()

    if not settings.elevenlabs_api_key:
        console.print("[yellow]Skipping ElevenLabs test - no API key configured[/yellow]")
        return None

    try:
        from elevenlabs import ElevenLabs
    except ImportError:
        console.print("[yellow]Skipping ElevenLabs test - elevenlabs package not installed[/yellow]")
        return None

    transcript = TEST_TRANSCRIPT.read_text()
    segments = parse_transcript(transcript)

    if not segments:
        raise ValueError("No speaker segments found in transcript")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "test_elevenlabs.mp3"

    voices = {
        1: settings.elevenlabs_voice_1,
        2: settings.elevenlabs_voice_2,
    }

    console.print("[bold]Testing ElevenLabs TTS...[/bold]")
    console.print(f"  Generating {len(segments)} segments...")

    client = ElevenLabs(api_key=settings.elevenlabs_api_key)
    audio_segments: list[AudioSegment] = []

    for i, (speaker, text) in enumerate(segments):
        voice_id = voices[speaker]

        # Generate audio using ElevenLabs
        audio_generator = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
        )

        # Collect the audio bytes from the generator
        audio_bytes = b"".join(audio_generator)

        # Convert to AudioSegment
        import io
        audio_segment = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
        audio_segments.append(audio_segment)

    # Concatenate with pauses (same logic as macOS)
    console.print("  Concatenating audio segments...")
    combined = audio_segments[0]
    for i, seg in enumerate(audio_segments[1:]):
        prev_text = segments[i][1]
        pause_ms = get_pause_duration(prev_text)
        combined += AudioSegment.silent(duration=pause_ms)
        combined += seg

    combined.export(str(output_path), format="mp3")
    console.print(f"[green]Audio saved:[/green] {output_path}")
    return output_path


def test_chatterbox_voices() -> Path | None:
    """Generate test audio using Chatterbox-Turbo TTS."""
    settings = get_settings()

    # Check if reference audio files exist
    voice_1_path = Path(settings.chatterbox_voice_1)
    voice_2_path = Path(settings.chatterbox_voice_2)

    if not voice_1_path.exists() or not voice_2_path.exists():
        console.print(
            "[yellow]Skipping Chatterbox test - reference audio files not found[/yellow]"
        )
        console.print(f"  Expected: {settings.chatterbox_voice_1}")
        console.print(f"  Expected: {settings.chatterbox_voice_2}")
        return None

    transcript = TEST_TRANSCRIPT.read_text()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "test_chatterbox.mp3"

    console.print("[bold]Testing Chatterbox-Turbo TTS...[/bold]")
    generate_audio_chatterbox(
        transcript=transcript,
        voice_1_ref=str(voice_1_path),
        voice_2_ref=str(voice_2_path),
        output_path=str(output_path),
    )
    return output_path


def test_google_cloud_voices() -> Path | None:
    """Generate test audio using Google Cloud Gemini TTS."""
    settings = get_settings()

    try:
        from google.cloud import texttospeech

        texttospeech.TextToSpeechClient()  # Test credentials
    except Exception as e:
        console.print(f"[yellow]Skipping Google Cloud test - {e}[/yellow]")
        return None

    transcript = TEST_TRANSCRIPT.read_text()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "test_google_cloud.mp3"

    console.print("[bold]Testing Google Cloud Gemini TTS...[/bold]")
    generate_audio_google_cloud(
        transcript=transcript,
        voice_1=settings.google_cloud_voice_1,
        voice_2=settings.google_cloud_voice_2,
        output_path=str(output_path),
        model=settings.google_cloud_model,
    )
    return output_path


def run_all_tests() -> dict[str, Path | None]:
    """Run all voice tests and return paths to generated files."""
    results: dict[str, Path | None] = {}

    # macOS test
    try:
        results["macos"] = test_macos_voices()
    except Exception as e:
        console.print(f"[red]macOS test failed:[/red] {e}")
        results["macos"] = None

    # ElevenLabs test
    try:
        results["elevenlabs"] = test_elevenlabs_voices()
    except Exception as e:
        console.print(f"[red]ElevenLabs test failed:[/red] {e}")
        results["elevenlabs"] = None

    # Chatterbox test
    try:
        results["chatterbox"] = test_chatterbox_voices()
    except Exception as e:
        console.print(f"[red]Chatterbox test failed:[/red] {e}")
        results["chatterbox"] = None

    # Google Cloud test
    try:
        results["google_cloud"] = test_google_cloud_voices()
    except Exception as e:
        console.print(f"[red]Google Cloud test failed:[/red] {e}")
        results["google_cloud"] = None

    return results
