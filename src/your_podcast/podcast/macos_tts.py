"""macOS text-to-speech using the `say` command with Premium/Siri voices."""

import random
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


def replace_filler_words(text: str) -> str:
    """Replace filler words that sound awkward with macOS TTS.

    Words like 'mmhmm' don't pronounce well, so we replace them with
    natural alternatives like 'Yeah', 'Yes', 'Right', 'Yep'.
    """
    replacements = ["Yeah", "Yes", "Right", "Yep"]

    # Match variations: mm-hmm, Mm-hmm, mmhmm, Mmhmm, mm hmm, etc.
    pattern = r"\b[Mm]m[- ]?[Hh]mm?\b"

    def get_replacement(match: re.Match) -> str:
        return random.choice(replacements)

    return re.sub(pattern, get_replacement, text)


def get_pause_duration(text: str) -> int:
    """Determine pause duration (ms) based on how a segment ends.

    Returns a contextually appropriate pause:
    - Questions: longer pause (thinking/processing time)
    - Ellipsis: medium-long pause (trailing off)
    - Exclamations: shorter pause (energetic continuation)
    - Statements: medium pause with slight variation
    """
    text = text.strip().rstrip('"\'')  # Remove trailing quotes

    if text.endswith("?"):
        # Questions need thinking time - 500-800ms
        return random.randint(500, 800)
    elif text.endswith("..."):
        # Trailing off - 400-600ms
        return random.randint(400, 600)
    elif text.endswith("!"):
        # Energetic - quick response 200-350ms
        return random.randint(200, 350)
    else:
        # Normal statement - 300-500ms with variation
        return random.randint(300, 500)


def _validate_voice(voice: str) -> None:
    """Check if a macOS voice is available.

    Raises:
        ValueError: If the voice is not found on the system.
    """
    result = subprocess.run(["say", "-v", voice, ""], capture_output=True, text=True)
    if result.returncode != 0 or "not found" in result.stderr.lower():
        raise ValueError(
            f"Voice '{voice}' not found. "
            f"Run 'say -v ?' to list available voices."
        )


def generate_audio_macos(
    transcript: str,
    voice_1: str,
    voice_2: str,
    output_path: str,
    rate: int = 165,
) -> str:
    """Generate podcast audio using macOS `say` command.

    Args:
        transcript: Podcastfy-formatted transcript with <Person1>/<Person2> tags.
        voice_1: macOS voice name for Person1 (e.g., "Zoe (Premium)").
        voice_2: macOS voice name for Person2 (e.g., "Lee (Premium)").
        output_path: Path to save the final combined audio file (.aiff).
        rate: Speech rate in words per minute (default 165).

    Returns:
        Path to the generated audio file.
    """
    # Validate voices upfront before processing
    _validate_voice(voice_1)
    _validate_voice(voice_2)

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

            # Clean up filler words that sound awkward with TTS
            cleaned_text = replace_filler_words(text)

            # Use macOS say command to generate audio segment
            cmd = [
                "say",
                "-v", voice,
                "-r", str(rate),
                "-o", str(segment_path),
                cleaned_text,
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

    # Concatenate segments with context-aware pauses between them
    console.print("[yellow]Concatenating audio segments with natural pauses...[/yellow]")
    combined = audio_segments[0]
    for i, seg in enumerate(audio_segments[1:]):
        # Add pause based on how previous segment ended
        prev_text = segments[i][1]  # i is offset by 1 due to slicing
        pause_ms = get_pause_duration(prev_text)
        combined += AudioSegment.silent(duration=pause_ms)
        combined += seg

    # Export as mp3
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(output), format="mp3")

    console.print(f"[green]Audio saved:[/green] {output}")
    return str(output)
