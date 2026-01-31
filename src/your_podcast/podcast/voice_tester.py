"""Voice testing module for comparing TTS providers."""

from pathlib import Path

from pydub import AudioSegment
from rich.console import Console

from your_podcast.podcast.macos_tts import (
    generate_audio_macos,
    get_pause_duration,
    parse_transcript,
)
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

    # Voice IDs from generator.py config
    voices = {
        1: "okH1aHncYRU2dc9TP3hV",  # Person1
        2: "WIX8boagHAO6uMUqxXLz",  # Person2
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

    return results
