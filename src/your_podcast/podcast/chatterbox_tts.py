"""Chatterbox TTS using the Chatterbox-Turbo model for voice cloning."""

import tempfile
from pathlib import Path

import torch
import torchaudio as ta
from pydub import AudioSegment
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from your_podcast.podcast.macos_tts import get_pause_duration, parse_transcript

console = Console()


def _get_device() -> str:
    """Auto-detect the best available device for Chatterbox."""
    if torch.cuda.is_available():
        return "cuda"
    elif torch.backends.mps.is_available():
        return "mps"
    else:
        return "cpu"


def generate_audio_chatterbox(
    transcript: str,
    voice_1_ref: str,
    voice_2_ref: str,
    output_path: str,
) -> str:
    """Generate podcast audio using Chatterbox-Turbo voice cloning.

    Args:
        transcript: Podcastfy-formatted transcript with <Person1>/<Person2> tags.
        voice_1_ref: Path to Person1 reference audio (~10 seconds).
        voice_2_ref: Path to Person2 reference audio (~10 seconds).
        output_path: Path to save the final combined audio file (.mp3).

    Returns:
        Path to the generated audio file.
    """
    from chatterbox.tts_turbo import ChatterboxTurboTTS

    # Validate reference audio files exist
    if not Path(voice_1_ref).exists():
        raise FileNotFoundError(f"Person1 reference audio not found: {voice_1_ref}")
    if not Path(voice_2_ref).exists():
        raise FileNotFoundError(f"Person2 reference audio not found: {voice_2_ref}")

    segments = parse_transcript(transcript)
    if not segments:
        raise ValueError("No speaker segments found in transcript")

    voices = {1: voice_1_ref, 2: voice_2_ref}

    # Detect device and load model
    device = _get_device()
    console.print(f"[yellow]Loading Chatterbox-Turbo model on {device}...[/yellow]")
    model = ChatterboxTurboTTS.from_pretrained(device=device)

    console.print(f"[yellow]Generating {len(segments)} audio segments...[/yellow]")
    console.print(f"  Person1: {voice_1_ref}")
    console.print(f"  Person2: {voice_2_ref}")

    audio_segments: list[AudioSegment] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Generating audio...", total=len(segments))

            for i, (speaker, text) in enumerate(segments):
                voice_ref = voices[speaker]
                segment_path = Path(tmp_dir) / f"segment_{i:04d}.wav"

                # Generate audio with Chatterbox
                wav = model.generate(text, audio_prompt_path=voice_ref)

                # Save segment as wav
                ta.save(str(segment_path), wav, model.sr)

                # Load into pydub for concatenation
                audio_segments.append(AudioSegment.from_file(str(segment_path), format="wav"))

                progress.update(task, advance=1)

    # Concatenate segments with context-aware pauses
    console.print("[yellow]Concatenating audio segments with natural pauses...[/yellow]")
    combined = audio_segments[0]
    for i, seg in enumerate(audio_segments[1:]):
        prev_text = segments[i][1]
        pause_ms = get_pause_duration(prev_text)
        combined += AudioSegment.silent(duration=pause_ms)
        combined += seg

    # Export as mp3
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(output), format="mp3")

    console.print(f"[green]Audio saved:[/green] {output}")
    return str(output)
