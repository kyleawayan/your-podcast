"""Google Cloud Text-to-Speech using Gemini 2.5 Flash TTS with multi-speaker support."""

import io
import os
from pathlib import Path

import google.generativeai as genai  # type: ignore[import-untyped]
from google.api_core.exceptions import InvalidArgument
from google.cloud import texttospeech
from pydub import AudioSegment
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from your_podcast.podcast.macos_tts import parse_transcript

console = Console()

# Configure Gemini for content sanitization (uses GEMINI_API_KEY from environment)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))


def sanitize_chunk_content(
    chunk: list[tuple[int, str]],
) -> list[tuple[int, str]]:
    """Use Gemini to rephrase chunk content to avoid TTS content moderation.

    Note: It looks like the TTS API has stricter content moderation than the transcript generation.
    Content that passes Gemini's transcript generation may still trigger TTS moderation
    filters. This function attempts to rephrase such content to make it TTS-safe.

    Args:
        chunk: List of (speaker_number, text) tuples.

    Returns:
        Sanitized chunk with rephrased content.
    """
    # Build the conversation text
    conversation = "\n".join(
        f"Speaker{speaker}: {text}" for speaker, text in chunk
    )

    prompt = f"""Rephrase the following podcast conversation to remove any content that might
trigger content moderation filters (profanity, explicit content, sensitive topics, etc.)
while preserving the meaning and flow of the conversation. Keep the same speaker labels.

Original conversation:
{conversation}

Rephrased conversation (keep the exact format "Speaker1: text" or "Speaker2: text"):"""

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)

        # Parse the response back into segments
        sanitized_chunk: list[tuple[int, str]] = []
        for line in response.text.strip().split("\n"):
            line = line.strip()
            if line.startswith("Speaker1:"):
                sanitized_chunk.append((1, line[9:].strip()))
            elif line.startswith("Speaker2:"):
                sanitized_chunk.append((2, line[9:].strip()))

        if sanitized_chunk:
            return sanitized_chunk
        else:
            # Fallback to original if parsing failed
            return chunk
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to sanitize content: {e}[/yellow]")
        return chunk


def chunk_segments(
    segments: list[tuple[int, str]], max_bytes: int = 4000
) -> list[list[tuple[int, str]]]:
    """Group segments into chunks that fit within the API byte limit.

    Args:
        segments: List of (speaker_number, text) tuples from parse_transcript.
        max_bytes: Maximum bytes per chunk (Google API limit is 4000 for turns).

    Returns:
        List of segment groups, each group fitting within max_bytes.
    """
    chunks: list[list[tuple[int, str]]] = []
    current_chunk: list[tuple[int, str]] = []
    current_size = 0

    for speaker, text in segments:
        # Estimate byte size for this segment
        segment_size = len(text.encode("utf-8"))

        if current_size + segment_size > max_bytes and current_chunk:
            # Start a new chunk
            chunks.append(current_chunk)
            current_chunk = [(speaker, text)]
            current_size = segment_size
        else:
            current_chunk.append((speaker, text))
            current_size += segment_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def generate_audio_google_cloud(
    transcript: str,
    voice_1: str,
    voice_2: str,
    output_path: str,
    model: str = "gemini-2.5-flash-preview-tts",
    prompt: str = "A natural podcast conversation between two hosts",
) -> str:
    """Generate podcast audio using Google Cloud Gemini TTS with multi-speaker support.

    Args:
        transcript: Podcastfy-formatted transcript with <Person1>/<Person2> tags.
        voice_1: Speaker ID for Person1 (e.g., "Kore").
        voice_2: Speaker ID for Person2 (e.g., "Charon").
        output_path: Path to save the final combined audio file (.mp3).
        model: TTS model name (default: gemini-2.5-flash-preview-tts).
        prompt: Style prompt for the TTS (optional).

    Returns:
        Path to the generated audio file.
    """
    client = texttospeech.TextToSpeechClient()

    segments = parse_transcript(transcript)
    if not segments:
        raise ValueError("No speaker segments found in transcript")

    # Group segments into chunks to stay under API limits
    chunks = chunk_segments(segments)

    console.print(f"[yellow]Generating audio with Google Cloud Gemini TTS...[/yellow]")
    console.print(f"  Model: {model}")
    console.print(f"  Person1: {voice_1}")
    console.print(f"  Person2: {voice_2}")
    console.print(f"  Segments: {len(segments)} in {len(chunks)} chunk(s)")

    # Map speaker number to alias
    speaker_aliases = {1: "Speaker1", 2: "Speaker2"}
    speaker_ids = {1: voice_1, 2: voice_2}

    # Set up voice configuration for both speakers
    multi_speaker_voice_config = texttospeech.MultiSpeakerVoiceConfig(
        speaker_voice_configs=[
            texttospeech.MultispeakerPrebuiltVoice(
                speaker_alias="Speaker1",
                speaker_id=voice_1,
            ),
            texttospeech.MultispeakerPrebuiltVoice(
                speaker_alias="Speaker2",
                speaker_id=voice_2,
            ),
        ]
    )

    voice_params = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        model_name=model,
        multi_speaker_voice_config=multi_speaker_voice_config,
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        sample_rate_hertz=24000,
    )

    audio_chunks: list[AudioSegment] = []
    skipped_chunks: list[int] = []

    def synthesize_chunk(chunk_data: list[tuple[int, str]]) -> bytes | None:
        """Try to synthesize a chunk, returns audio bytes or None on failure."""
        turns = []
        for speaker, text in chunk_data:
            turn = texttospeech.MultiSpeakerMarkup.Turn(
                speaker=speaker_aliases[speaker],
                text=text,
            )
            turns.append(turn)

        synthesis_input = texttospeech.SynthesisInput(
            multi_speaker_markup=texttospeech.MultiSpeakerMarkup(turns=turns),
            prompt=prompt,
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice_params,
            audio_config=audio_config,
        )
        return response.audio_content

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Generating audio...", total=len(chunks))

        for chunk_idx, chunk in enumerate(chunks):
            audio_content = None

            # First attempt: try normal synthesis
            try:
                audio_content = synthesize_chunk(chunk)
            except InvalidArgument as e:
                if "sensitive or harmful content" in str(e) or "400" in str(e):
                    console.print(
                        f"\n[yellow]Chunk {chunk_idx + 1}: Content moderation triggered, "
                        f"attempting to sanitize...[/yellow]"
                    )

                    # Second attempt: sanitize content and retry
                    try:
                        sanitized_chunk = sanitize_chunk_content(chunk)
                        audio_content = synthesize_chunk(sanitized_chunk)
                        console.print(
                            f"[green]Chunk {chunk_idx + 1}: Sanitized version succeeded[/green]"
                        )
                    except Exception as retry_error:
                        console.print(
                            f"[red]Chunk {chunk_idx + 1}: Still failed after sanitization, "
                            f"skipping ({retry_error})[/red]"
                        )
                        skipped_chunks.append(chunk_idx + 1)
                else:
                    raise

            if audio_content:
                audio_segment = AudioSegment.from_file(
                    io.BytesIO(audio_content), format="wav"
                )
                audio_chunks.append(audio_segment)

            progress.update(task, advance=1)

    if skipped_chunks:
        console.print(
            f"[yellow]Warning: Skipped {len(skipped_chunks)} chunk(s) due to content "
            f"moderation: {skipped_chunks}[/yellow]"
        )

    if not audio_chunks:
        raise ValueError(
            "All chunks failed content moderation. Cannot generate audio."
        )

    # Concatenate audio chunks
    console.print("[yellow]Concatenating audio chunks...[/yellow]")
    combined = audio_chunks[0]
    for chunk in audio_chunks[1:]:
        combined += chunk

    # Export as MP3
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(output), format="mp3")

    console.print(f"[green]Audio saved:[/green] {output}")
    return str(output)
