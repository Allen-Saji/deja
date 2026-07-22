from pathlib import Path


def test_lambda_image_uses_writable_hugging_face_cache() -> None:
    dockerfile = Path("Dockerfile").read_text()

    assert 'HF_HOME="/tmp/huggingface"' in dockerfile
