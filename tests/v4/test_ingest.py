from codex_claude_orchestrator.v4.ingest import OutputIngestor


def test_output_ingestor_slices_current_turn_after_prior_marker():
    ingestor = OutputIngestor()
    text = (
        "old review\n"
        "<<<CODEX_TURN_DONE crew=crew-1 worker=w phase=review round=1>>>\n"
        "current output\n"
        "<<<CODEX_TURN_DONE crew=crew-1 worker=w phase=review round=2>>>\n"
        "prompt tail"
    )

    current = ingestor.current_turn_text(
        text,
        expected_marker="<<<CODEX_TURN_DONE crew=crew-1 worker=w phase=review round=2>>>",
    )

    assert current == "current output\n"


def test_output_ingestor_ignores_incomplete_current_marker():
    ingestor = OutputIngestor()
    text = "current output\n<<<CODEX_TURN_DONE"

    current = ingestor.current_turn_text(
        text,
        expected_marker="<<<CODEX_TURN_DONE crew=crew-1 worker=w phase=review round=2>>>",
    )

    assert current == text


def test_output_ingestor_handles_empty_expected_marker():
    ingestor = OutputIngestor()
    text = (
        "old review\n"
        "<<<CODEX_TURN_DONE crew=crew-1 worker=w phase=review round=1>>>\n"
        "current output\n"
    )

    current = ingestor.current_turn_text(text, expected_marker="")

    assert current == "current output\n"


def test_output_ingestor_builds_chunk_events():
    ingestor = OutputIngestor()

    events = ingestor.to_output_events(
        turn_id="turn-1",
        worker_id="worker-1",
        text="a\nb",
        artifact_ref="turns/turn-1/transcript.txt",
    )

    assert [event.payload["text"] for event in events] == ["a", "b"]
    assert events[0].artifact_refs == ["turns/turn-1/transcript.txt"]
