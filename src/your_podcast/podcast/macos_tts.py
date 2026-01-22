"""macOS text-to-speech using the `say` command with Premium/Siri voices."""

import re
import subprocess
import tempfile
from pathlib import Path

from pydub import AudioSegment
from rich.console import Console

console = Console()


def parse_transcript(transcript: str) -> list[tuple[int, str]]:
    """Parse a Podcastfy transcript into (speaker, text) segments.

    Podcastfy transcripts use <Person1>...</Person1> and <Person2>...</Person2> tags.

    Returns:
        List of (speaker_number, text) tuples where speaker_number is 1 or 2.
    """
    segments: list[tuple[int, str]] = []
    pattern = r"<Person(\d)>(.*?)</Person\1>"
    for match in re.finditer(pattern, transcript, re.DOTALL):
        speaker = int(match.group(1))
        text = match.group(2).strip()
        if text:
            segments.append((speaker, text))
    return segments


def generate_audio_macos(
    transcript: str,
    voice_1: str,
    voice_2: str,
    output_path: str,
    rate: int = 180,
) -> str:
    """Generate podcast audio using macOS `say` command.

    Args:
        transcript: Podcastfy-formatted transcript with <Person1>/<Person2> tags.
        voice_1: macOS voice name for Person1 (e.g., "Ava (Premium)").
        voice_2: macOS voice name for Person2 (e.g., "Zoe (Premium)").
        output_path: Path to save the final combined audio file (.aiff).
        rate: Speech rate in words per minute (default 180).

    Returns:
        Path to the generated audio file.
    """
    segments = parse_transcript(transcript)
    if not segments:
        raise ValueError("No speaker segments found in transcript")

    voices = {1: voice_1, 2: voice_2}
    audio_segments: list[AudioSegment] = []

    console.print(f"[yellow]Generating {len(segments)} audio segments with macOS voices...[/yellow]")
    console.print(f"  Person1: {voice_1}")
    console.print(f"  Person2: {voice_2}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        for i, (speaker, text) in enumerate(segments):
            voice = voices[speaker]
            segment_path = Path(tmp_dir) / f"segment_{i:04d}.aiff"

            # Use macOS say command to generate audio segment
            cmd = [
                "say",
                "-v", voice,
                "-r", str(rate),
                "-o", str(segment_path),
                text,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(
                    f"macOS say command failed for segment {i} (voice: {voice}): "
                    f"{result.stderr}"
                )

            audio_segments.append(AudioSegment.from_file(str(segment_path), format="aiff"))

            if (i + 1) % 10 == 0:
                console.print(f"  [dim]Processed {i + 1}/{len(segments)} segments...[/dim]")

    # Concatenate all segments
    console.print("[yellow]Concatenating audio segments...[/yellow]")
    combined = audio_segments[0]
    for seg in audio_segments[1:]:
        combined += seg

    # Export as mp3
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(output), format="mp3")

    console.print(f"[green]Audio saved:[/green] {output}")
    return str(output)
